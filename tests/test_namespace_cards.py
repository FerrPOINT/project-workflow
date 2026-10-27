"""Exercise the actual hydrated namespace card renderer at its visible-text boundary."""

import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from tests import test_ui_shell_template as shell_templates


class TemplateFragments(HTMLParser):
    """Read the real macro-rendered inert fragments used by the DOM adapter."""

    def __init__(self, html):
        super().__init__()
        self.fragments = {}
        self.active = None
        self.stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "template":
            self.active = attrs.get("id")
            self.stack = []
        elif self.active:
            node = {"tag": tag, "attrs": attrs, "children": []}
            if self.stack:
                self.stack[-1]["children"].append(node)
            else:
                self.fragments[self.active] = node
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag == "template":
            self.active = None
            self.stack = []
        elif self.active and self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()


def template_dom():
    namespace = dict(id=17, name="QA", cli_command="qa-first", theme_icon="folder", theme_color="#123456", task_count=0)
    html = shell_templates.SharedShellTemplateTests().render_shell(
        [namespace], template="namespaces.html", selected_namespace=namespace,
        edited_namespace=namespace, create_mode=False,
    )
    fragments = TemplateFragments(html).fragments
    # The product's DOM operations run in Node; the markup comes from real Jinja/Base.
    return "const fragmentTrees=" + json.dumps(fragments, ensure_ascii=False) + ";\n" + r"""
class Node {
  constructor(tag='span',attrs={},children=[]){
    this.tag=tag;this.attrs={...attrs};this.children=children;this.value='';
    this.dataset=Object.fromEntries(Object.entries(attrs).filter(([key])=>key.startsWith('data-'))
      .map(([key,value])=>[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase()),value]));
    this.style={setProperty(name,value){this[name]=value;}};
    for(const pair of (attrs.style??'').split(';')){const colon=pair.indexOf(':');
      if(colon>=0)this.style.setProperty(pair.slice(0,colon).trim(),pair.slice(colon+1).trim());}
  }
  get className(){return this.attrs.class??'';} set className(value){this.attrs.class=value;}
  appendChild(child){this.children.push(child);return child;} append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(name,value){this.attrs[name]=value;}
  set textContent(value){this.value=String(value);this.children=[];}
  get textContent(){return this.value+this.children.map(child=>child.textContent).join('');}
  cloneNode(deep){return new Node(this.tag,this.attrs,deep?this.children.map(child=>child.cloneNode(true)):[]);}
  get firstElementChild(){return this.children[0]??null;}
  querySelector(tag){for(const child of this.children){if(tag.startsWith('.')?
    child.className.split(/\s+/).includes(tag.slice(1)):child.tag===tag)return child;
    const match=child.querySelector(tag);if(match)return match;}return null;}
}
function element(tree){return new Node(tree.tag,tree.attrs,tree.children.map(element));}
const fragments=Object.fromEntries(Object.entries(fragmentTrees).map(([id,tree])=>
  [id,{content:{firstElementChild:element(tree)}}]));
const nav=new Node();const other={classList:{toggle(){}}};
const document={createElement:tag=>new Node(tag),createElementNS:(_ns,tag)=>new Node(tag),
  getElementById:id=>fragments[id]??(id==='namespaceNav'?nav:other)};
"""


def test_hydrated_namespace_cards_show_names_without_an_extra_cli_command():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/namespaces.html").read_text(
        encoding="utf-8"
    )
    render = template[
        template.index("function renderNamespaceNav()") : template.index("function renderNamespacePagePicker()")
    ]
    script = template_dom() + """
const namespaceStore=[{id:17,name:'QA: инженер интеграций',cli_command:'qa-first',theme_color:'#ffffff',task_count:0},
  {id:23,name:'qa-second',cli_command:'qa-second',task_count:0}];
const defaultNamespaceThemeColor='#123456';const defaultNamespaceThemeIcon='folder';
const namespaceIconPaths={folder:'M0 0h1'};
const pluralizeRu=()=> '0 задач';const selectNamespace=()=>{};
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script + render + "\nrenderNamespaceNav();console.log(JSON.stringify(nav.children.map(node=>"
        "({id:node.dataset.namespaceId,text:node.textContent,mark:node.children[0].className,"
        "size:node.children[0].dataset.size,color:node.children[0].style['--base-icon-mark-color']}))));",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {
            "id": "17",
            "text": "QA: инженер интеграций0 задач",
            "mark": "base-icon-mark",
            "size": "md",
            "color": "#ffffff",
        },
        {"id": "23", "text": "qa-second0 задач", "mark": "base-icon-mark", "size": "md", "color": "#123456"},
    ]


def test_card_template_clones_keep_distinct_ids_one_callback_and_independent_marks():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/namespaces.html").read_text(
        encoding="utf-8"
    )
    renderer = template[
        template.index("function renderNamespaceNav()") : template.index("function renderNamespacePagePicker()")
    ]
    script = template_dom() + r"""
const namespaceStore=[{id:17,name:'Same name',task_count:3},{id:23,name:'Same name',task_count:0}];
const defaultNamespaceThemeColor='#123456',defaultNamespaceThemeIcon='folder';
const namespaceIconPaths={folder:'M0 0h1'},calls=[];
const pluralizeRu=count=>String(count)+' задач',selectNamespace=id=>calls.push(id);
""" + renderer + r"""
renderNamespaceNav();const before=calls.length;
nav.children[1].onclick();
nav.children[0].firstElementChild.style.setProperty('--base-icon-mark-color','#ffffff');
console.log(JSON.stringify({before,calls,ids:nav.children.map(x=>x.dataset.namespaceId),
  types:nav.children.map(x=>x.attrs.type),
  controls:nav.children.map(x=>x.attrs['aria-controls']),
  callbacks:nav.children.map(x=>typeof x.onclick),
  templateHandler:fragments['namespace-card-template'].content.firstElementChild.attrs.onclick??null,
  secondColor:nav.children[1].firstElementChild.style['--base-icon-mark-color']}));
"""
    result = subprocess.run(["node", "--input-type=module", "-"], input=script,
                            text=True, encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "before": 0, "calls": [23], "ids": ["17", "23"], "types": ["button", "button"],
        "controls": ["namespaceForm", "namespaceForm"], "callbacks": ["function", "function"],
        "templateHandler": None, "secondColor": "#123456",
    }


def test_profession_choice_uses_the_same_base_mark_without_changing_label_or_icon_data():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html").read_text(
        encoding="utf-8"
    )
    renderer = template[
        template.index("function renderNamespaceChoice(") : template.index("let confirmedProfessionId")
    ].replace("{{ project_icon_paths | tojson }}", json.dumps({"folder": "M0 0h1", "workflow": "M1 1h2"}))
    script = template_dom()
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script
        + renderer
        + """
const rows=[{label:'Первая профессия',dataset:{color:'#ffffff',icon:'workflow'}},
            {label:'Вторая профессия',dataset:{}}].map(option=>{
  const label=renderNamespaceChoice(option,'option'),mark=label.children[0];
  return {name:label.children[1].textContent,mark:mark.className,size:mark.dataset.size,
          color:mark.style['--base-icon-mark-color']??'var(--color-accent)',hidden:mark.attrs['aria-hidden'],
          path:mark.children[0].children[0].attrs.d};
});console.log(JSON.stringify(rows));
""",
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {
            "name": "Первая профессия",
            "mark": "base-icon-mark",
            "size": "sm",
            "color": "#ffffff",
            "hidden": "true",
            "path": "M1 1h2",
        },
        {
            "name": "Вторая профессия",
            "mark": "base-icon-mark",
            "size": "sm",
            "color": "var(--color-accent)",
            "hidden": "true",
            "path": "M0 0h1",
        },
    ]


def test_dynamic_marks_and_counts_preserve_identity_and_do_not_mutate_templates_or_records():
    root = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
    page = (root / "namespaces.html").read_text(encoding="utf-8")
    base = (root / "base.html").read_text(encoding="utf-8")
    render = page[page.index("function renderNamespaceNav()") : page.index("function renderNamespacePagePicker()")]
    pluralize = base[base.index("function pluralizeRu(") : base.index("{% block extra_script %}")]
    script = template_dom() + """
const namespaceStore=[
 {id:17,name:'Same <name>',cli_command:'first',theme_icon:'workflow',theme_color:'#ffffff',task_count:1},
 {id:23,name:'Same <name>',cli_command:'second',theme_icon:'missing',task_count:12},
 {id:99,name:'Длинное имя '+ 'профессии '.repeat(20),theme_icon:'bug',theme_color:'#0EA5E9',task_count:2}];
const defaultNamespaceThemeColor='#123456',defaultNamespaceThemeIcon='folder';
const namespaceIconPaths={folder:'M0 0h1',workflow:'M1 1h2',bug:'M2 2h3'};
const selected=[];const selectNamespace=id=>selected.push(id);
const originalRecords=JSON.stringify(namespaceStore);
const originalTemplates=JSON.stringify(fragments);
""" + pluralize + render + """
renderNamespaceNav();
if(selected.length)throw Error('Rendering triggered selection');
const rows=nav.children.map(button=>({id:button.dataset.namespaceId,name:button.children[1].children[0].textContent,
 count:button.children[1].children[1].children[0].textContent,
 badge:button.children[1].children[1].children[0].dataset,
 color:button.children[0].style['--base-icon-mark-color'],
 path:button.children[0].querySelector('path').attrs.d,hidden:button.children[0].attrs['aria-hidden'],
 controls:button.attrs['aria-controls'],pressed:button.attrs['aria-pressed']}));
nav.children[1].onclick();
if(nav.children[0].children[0]===nav.children[1].children[0])throw Error('Shared mutable mark');
if(JSON.stringify(namespaceStore)!==originalRecords||JSON.stringify(fragments)!==originalTemplates)
 throw Error('Renderer changed source data');
if(fragments['namespace-card-template'].content.firstElementChild.querySelector('path').attrs.d==='M1 1h2')
 throw Error('Renderer changed reusable fragment');
namespaceStore.splice(0);renderNamespaceNav();
console.log(JSON.stringify({rows,selected,empty:nav.children.length}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input=script, text=True, encoding="utf-8",
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["selected"] == [23]
    assert actual["empty"] == 0
    assert [row["id"] for row in actual["rows"]] == ["17", "23", "99"]
    assert [row["name"] for row in actual["rows"][:2]] == ["Same <name>", "Same <name>"]
    assert len(actual["rows"][2]["name"]) > 150
    assert [row["count"] for row in actual["rows"]] == ["1 задача", "12 задач", "2 задачи"]
    assert [row["path"] for row in actual["rows"]] == ["M1 1h2", "M0 0h1", "M2 2h3"]
    assert [row["color"] for row in actual["rows"]] == ["#ffffff", "#123456", "#0EA5E9"]
    for row in actual["rows"]:
        assert row["badge"] == {"tone": "muted", "appearance": "inline"}
        assert row["hidden"] == "true"
        assert row["controls"] == "namespaceForm"
        assert row["pressed"] == "false"


def test_visual_icon_picker_keeps_glyphs_and_accessible_names_with_independent_clones():
    page = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/namespaces.html").read_text(
        encoding="utf-8"
    )
    render = page[page.index("function renderNamespaceIconChoice(") : page.index("function currentPayload(")]
    script = template_dom() + """
const namespaceIconPaths={folder:'M0 0h1',workflow:'M1 1h2'},defaultNamespaceThemeIcon='folder';
const defaultNamespaceThemeColor='#123456';other.value='#FFFFFF';
""" + render + """
const rows=[{value:'workflow',label:'Workflow <icon>'},{value:'missing',label:'Fallback'}].map(option=>{
 const node=renderNamespaceIconChoice(option);return{path:node.children[0].querySelector('path').attrs.d,
   size:node.children[0].dataset.size,color:node.children[0].style['--base-icon-mark-color'],
   foreground:node.children[0].querySelector('svg').style.color??null,mark:node.children[0].className,
   name:node.children[1].textContent,hiddenName:node.children[1].className};});
console.log(JSON.stringify(rows));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input=script, text=True, encoding="utf-8",
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert [row["path"] for row in rows] == ["M1 1h2", "M0 0h1"]
    assert [row["name"] for row in rows] == ["Workflow <icon>", "Fallback"]
    for row in rows:
        assert row["size"] == "sm"
        assert row["mark"] == "base-icon-mark"
        assert row["color"] == "#FFFFFF"
        assert row["foreground"] is None
        assert row["hiddenName"] == "base-visually-hidden"
