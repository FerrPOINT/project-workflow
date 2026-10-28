"""Exercise the actual hydrated namespace card renderer at its visible-text boundary."""
import json
import subprocess
from pathlib import Path


def test_hydrated_namespace_cards_show_names_without_an_extra_cli_command():
    template = (
        Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/controllers/namespaces.js"
    ).read_text(encoding="utf-8")
    render = template[
        template.index("function renderNamespaceNav()"):
        template.index("function renderNamespacePagePicker()")
    ]
    script = """
class Node {
  constructor(){this.children=[];this.dataset={};this.style={setProperty(){}};this.value='';}
  appendChild(child){this.children.push(child);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  set textContent(value){this.value=value;}
  get textContent(){return this.value+this.children.map(child=>child.textContent).join('');}
}
const nav=new Node();const document={createElement:()=>new Node(),getElementById:id=>
  id==='namespaceNav'?nav:{classList:{toggle(){}}}};
const namespaceStore=[{id:17,name:'QA: инженер интеграций',cli_command:'qa-first',task_count:0},
  {id:23,name:'qa-second',cli_command:'qa-second',task_count:0}];
const defaultNamespaceThemeColor='#123456';const namespaceIconSvg=()=>'';
const pluralizeRu=()=> '0 задач';const selectNamespace=()=>{};
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script + render + "\nrenderNamespaceNav();console.log(JSON.stringify(nav.children.map(node=>"
        "({id:node.dataset.namespaceId,text:node.textContent}))));",
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {"id": "17", "text": "QA: инженер интеграций0 задач"},
        {"id": "23", "text": "qa-second0 задач"},
    ]
