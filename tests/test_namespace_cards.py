"""Exercise the actual hydrated namespace card renderer at its visible-text boundary."""

import json
import subprocess
from pathlib import Path


def test_hydrated_namespace_cards_show_names_without_an_extra_cli_command():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/namespaces.html").read_text(
        encoding="utf-8"
    )
    render = template[
        template.index("function renderNamespaceNav()") : template.index("function renderNamespacePagePicker()")
    ]
    script = """
class Node {
  constructor(){this.children=[];this.dataset={};this.style={setProperty(name,value){this[name]=value;}};this.value='';}
  appendChild(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  set textContent(value){this.value=value;}
  get textContent(){return this.value+this.children.map(child=>child.textContent).join('');}
}
const nav=new Node();const document={createElement:()=>new Node(),getElementById:id=>
  id==='namespaceNav'?nav:{classList:{toggle(){}}}};
const namespaceStore=[{id:17,name:'QA: инженер интеграций',cli_command:'qa-first',theme_color:'#ffffff',task_count:0},
  {id:23,name:'qa-second',cli_command:'qa-second',task_count:0}];
const defaultNamespaceThemeColor='#123456';const namespaceIconSvg=()=>'';
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


def test_profession_choice_uses_the_same_base_mark_without_changing_label_or_icon_data():
    template = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html").read_text(
        encoding="utf-8"
    )
    renderer = template[
        template.index("function renderNamespaceChoice(") : template.index("let confirmedProfessionId")
    ].replace("{{ project_icon_paths | tojson }}", json.dumps({"folder": "M0 0h1", "workflow": "M1 1h2"}))
    script = """
class Node {
  constructor(){this.children=[];this.dataset={};this.attrs={};this.style={setProperty(name,value){this[name]=value;}};}
  setAttribute(name,value){this.attrs[name]=value;}
  append(...children){this.children.push(...children);}
}
const document={createElement:()=>new Node(),createElementNS:()=>new Node()};
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script
        + renderer
        + """
const rows=[{label:'Первая профессия',dataset:{color:'#ffffff',icon:'workflow'}},
            {label:'Вторая профессия',dataset:{}}].map(option=>{
  const label=renderNamespaceChoice(option,'option'),mark=label.children[0];
  return {name:label.children[1].textContent,mark:mark.className,size:mark.dataset.size,
          color:mark.style['--base-icon-mark-color']??null,hidden:mark.attrs['aria-hidden'],
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
            "color": None,
            "hidden": "true",
            "path": "M0 0h1",
        },
    ]
