"""Render the product shell with its pinned Base resources, without a runtime DB."""

import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from unittest import TestCase

from jinja2 import Environment, FileSystemLoader, select_autoescape

from project_workflow.interfaces.ui.templates import env as product_template_environment


class Elements(HTMLParser):
    """Collect active markup, excluding script text and inert template content."""

    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.template_depth = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "template":
            self.template_depth += 1
        if self.template_depth:
            return
        self.elements.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag == "template" and self.template_depth:
            self.template_depth -= 1


class SharedShellTemplateTests(TestCase):
    def test_element_inventory_excludes_nested_inert_templates_but_keeps_active_neighbors(self):
        html = '<input id="before"><template><input id="inert"><template><button></button></template></template>'
        html += '<textarea id="after"></textarea><script>"<button>not markup</button>"</script>'
        elements = Elements(html).elements
        self.assertEqual([attrs.get("id") for tag, attrs in elements if tag != "script"], ["before", "after"])

    def test_error_page_preserves_owner_content_and_back_navigation_in_shared_components(self):
        for status in [404, 422, 503]:
            with self.subTest(status=status):
                html = self.render_shell(
                    [], template="error.html", status_code=status,
                    title="Owner <title>", message="Owner <message>",
                    back_url="/phases?profession_id=73&workflow_id=19",
                    back_label="К фазам <73>",
                )
                elements = Elements(html).elements
                headings = [attrs for tag, attrs in elements if tag == "h1"]
                self.assertEqual(len(headings), 1)
                self.assertIn("base-page-title", headings[0].get("class", "").split())
                states = [attrs for _, attrs in elements if attrs.get("data-page-state") == "error"]
                self.assertEqual(len(states), 1)
                self.assertEqual(states[0]["role"], "alert")
                back = next(attrs for tag, attrs in elements if tag == "a" and
                            attrs.get("href") == "/workflow/phases?profession_id=73&workflow_id=19")
                self.assertIn("base-button", back["class"].split())
                self.assertNotIn("onclick", back)
                self.assertIn(f"HTTP {status}", html)
                self.assertIn("Owner &lt;title&gt;", html)
                self.assertIn("Owner &lt;message&gt;", html)
                self.assertIn("← К фазам &lt;73&gt;", html)
                self.assertNotIn("base-state-retry-icon", html.split("<body", 1)[1])

    def test_workflow_unknown_write_readback_uses_shared_button_without_changing_owner_action(self):
        for can_administer in [True, False]:
            with self.subTest(can_administer=can_administer):
                html = self.render_shell(
                    [], template="workflows.html", workflows=[],
                    selected_workflow=None, selected_namespace=None,
                    phases=[], phase_blocks=[], modes=[], phase_count=0,
                    can_administer=can_administer,
                )
                elements = Elements(html).elements
                retry = [attrs for tag, attrs in elements
                         if tag == "button" and attrs.get("onclick") == "retryWorkflowReadback()"]
                self.assertEqual(len(retry), 1)
                self.assertEqual(retry[0]["type"], "button")
                self.assertIn("base-control", retry[0].get("class", "").split())
                self.assertIn("base-button", retry[0].get("class", "").split())
                error = next(attrs for _, attrs in elements if attrs.get("id") == "workflowReadbackError")
                self.assertEqual(error["role"], "alert")
                self.assertIn("hidden", error)

    def test_dashboard_metrics_reuse_base_instead_of_a_product_skin(self):
        source = (Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("base_ui.metric(", source)
        self.assertIsNone(re.search(r"\.metric-(?:card|label|value|verdict)\b", source))
        self.assertIn(".dashboard-grid{", source)  # Product composition is retained.

    def test_shell_styles_delegate_layout_and_retired_primitives_to_base(self):
        source = (
            Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates/base.html"
        ).read_text(encoding="utf-8")
        css = source.split("<style>", 1)[1].split("</style>", 1)[0]
        retired = (
            "brand-text|brand-name|brand-subname|header-title-group|header-actions|theme-select|"
            "namespace-icon-action|phase-detail-header|tabs|tab|sidebar-status-label|brand-link|header-title|section-heading|"
            "dot|status|status-dot|status-done|status-active|status-wait|status-block|row|btn-group"
        )
        self.assertIsNone(re.search(r"\.\b(?:" + retired + r")\b(?![-\w])", css))
        self.assertIsNone(re.search(r"\.(?:page-frame|page-wide|page-detail|page-readable|page-split)\b", css))
        self.assertIn(".timeline-row{", css)
        self.assertNotIn(".row-actions{", css)
        html = self.render_shell([])
        elements = Elements(html).elements
        self.assertEqual(sum("page-frame" in attrs.get("class", "").split() for _, attrs in elements), 1)
        self.assertIn('{% include "base/base-ui.css" %}', source)

    def test_home_link_and_page_title_use_the_shared_controls_with_native_semantics(self):
        html = self.render_shell([])
        elements = Elements(html).elements
        home = next(attrs for tag, attrs in elements if tag == "a" and attrs.get("aria-label") == "Project Workflow")
        self.assertEqual(home["href"], "/workflow/")
        self.assertTrue({"base-control", "base-button", "base-icon-control"} <= set(home["class"].split()))
        self.assertEqual(home["data-variant"], "ghost")
        self.assertEqual(home["data-size"], "icon")
        self.assertNotIn("type", home)
        self.assertNotIn("onclick", home)
        heading = next(attrs for tag, attrs in elements if tag == "h1")
        self.assertIn("base-page-title", heading["class"].split())

    def test_dashboard_shared_headings_links_and_empty_states_keep_namespace_navigation(self):
        html = self.render_shell(
            [{"id": 73, "name": "Profession", "task_count": 0}],
            template="dashboard.html",
            stats=dict(namespaces=1, tasks=0, active=0, done=0, verdicts={}),
            open_tasks=[],
        )
        elements = Elements(html).elements
        headings = {attrs.get("id"): attrs for tag, attrs in elements if tag == "h2"}
        for name in ["dashboardTasksTitle", "dashboardNamespacesTitle"]:
            self.assertIn("base-section-title", headings[name]["class"].split())
        links = [attrs for tag, attrs in elements if tag == "a" and "base-text-link" in attrs.get("class", "").split()]
        self.assertEqual(
            [attrs["href"] for attrs in links],
            ["/workflow/tasks?profession_id=73", "/workflow/namespaces"],
        )
        self.assertEqual(sum(attrs.get("data-page-state") == "empty" for _, attrs in elements), 1)
        self.assertIn("Незавершённых задач нет.", html)

    def test_dashboard_resource_text_uses_base_with_escaped_labels_and_distinct_links(self):
        namespaces = [dict(id=value, name="Same <name>", task_count=value) for value in [7, 9]]
        tasks = [
            dict(task_key="WK-7", title="Title <script>text</script>", namespace_id=7,
                 namespace_name="Same <name>", workflow_name="Flow <7>", status_label="В работе"),
            dict(task_key="WK-9", title="", namespace_id=9,
                 namespace_name="Same <name>", workflow_name=None, status_label="Ожидает"),
        ]
        html = self.render_shell(
            namespaces, template="dashboard.html", open_tasks=tasks,
            stats=dict(namespaces=2, tasks=2, active=1, done=0, verdicts={}),
        )
        elements = Elements(html).elements
        titles = [attrs for _, attrs in elements
                  if "base-resource-title" in attrs.get("class", "").split()]
        self.assertEqual(sum(attrs.get("data-technical") != "true" for attrs in titles), 4)
        keys = [attrs for attrs in titles if attrs.get("data-technical") == "true"]
        self.assertEqual(len(keys), 2)
        self.assertEqual([attrs.get("data-tone") for attrs in keys], ["accent", "accent"])
        self.assertEqual(sum("base-resource-description" in attrs.get("class", "").split()
                             for _, attrs in elements), 7)
        links = [attrs["href"] for tag, attrs in elements
                 if tag == "a" and ("data-task-key" in attrs or "data-namespace-id" in attrs)]
        self.assertEqual(links, ["/workflow/task/WK-7?profession_id=7",
                                "/workflow/task/WK-9?profession_id=9",
                                "/workflow/namespaces?profession_id=7",
                                "/workflow/namespaces?profession_id=9"])
        self.assertIn("Title &lt;script&gt;text&lt;/script&gt;", html)
        self.assertIn("Flow &lt;7&gt;", html)
        self.assertNotIn("<script>text</script>", html)

    def test_instructions_use_one_shared_header_and_exact_namespace_return_url(self):
        for name in ["Phase <name>", "Очень длинное название фазы " * 8]:
            for namespace in [None, dict(id=73, code="QA", name="QA")]:
                with self.subTest(name=name, namespace=namespace):
                    html = self.render_shell(
                        [], template="instructions.html",
                        phase=dict(id=4, name=name), selected_namespace=namespace,
                        instruction_groups=[],
                    )
                    elements = Elements(html).elements
                    headers = [attrs for _, attrs in elements
                               if "base-page-header" in attrs.get("class", "").split()]
                    self.assertEqual(len(headers), 1)
                    titles = [attrs for tag, attrs in elements if tag == "h1"]
                    self.assertEqual(len(titles), 1)
                    self.assertIn("base-page-title", titles[0].get("class", "").split())
                    self.assertIn("Инструкции фазы " + escape(name), html)
                    expected = "/workflow/phase/4" + ("?profession_id=73" if namespace else "")
                    links = [attrs for tag, attrs in elements
                             if tag == "a" and attrs.get("href", "").startswith("/workflow/phase/4")]
                    self.assertEqual(len(links), 1)
                    self.assertEqual(links[0]["href"], expected)
                    self.assertIn("base-button", links[0].get("class", "").split())
                    self.assertNotIn("onclick", links[0])
                    empty = [attrs for _, attrs in elements if attrs.get("data-page-state") == "empty"]
                    self.assertEqual(len(empty), 1)
                    self.assertIn("Инструкций пока нет.", html)
                    for retired in ["instructions-mobile", "instructions-desktop-title", "instructions-context"]:
                        self.assertNotIn(retired, html)

    def render_instruction_editor(self, parallel=False, template="phase_detail.html"):
        instructions = [
            dict(
                id=31,
                step_num=1,
                description="First <step>",
                execution_type="sync",
                skills=["tool×safe", '<script> "quoted"'],
            ),
            dict(
                id=32,
                step_num=2,
                description="Second step",
                execution_type="parallel" if parallel else "sync",
                skills=[],
            ),
        ]
        phase = dict(
            id=4,
            code="PHASE",
            name="Phase <name>",
            description="Description",
            workflow_id=3,
            mode_id=None,
            execution_type="sync",
            parallel_with_phase_id=None,
            instructions=instructions,
            checks=[dict(id=51, description="Check")],
            evidence=[dict(id=61, description="Evidence")],
        )
        return self.render_shell(
            [],
            template=template,
            phase=phase,
            selected_namespace=None,
            rollback_target_phase=None,
            parallel_candidates=[],
            instruction_groups=[instructions] if parallel else [[item] for item in instructions],
        )

    def render_shell(
        self,
        namespaces,
        services_source="fallback-unreachable",
        other_services=None,
        template="base.html",
        commands=None,
        **page_context,
    ):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(
            loader=FileSystemLoader(templates),
            autoescape=select_autoescape(["html"]),
        )
        environment.filters.update(product_template_environment.filters)
        environment.globals.update(product_template_environment.globals)
        environment.globals.update(
            ui_base_path=lambda: "/workflow",
            platform_branding_url=lambda: "/workflow/api/platform/branding",
        )
        # These composition fixtures exercise the explicit administrative view.
        # Current-role request admission is covered by test_human_role_views.
        page_context.setdefault("can_administer", True)
        return environment.get_template(template).render(
            page="namespace",
            project_icon_paths={},
            namespaces=namespaces,
            namespace_cookie_name="qa-namespace",
            namespace_cookie_secure=False,
            commands=commands or [],
            theme_namespace=namespaces[0] if namespaces else None,
            other_services=other_services
            if other_services is not None
            else [
                {"key": "project-workflow", "label": "Workflow", "url": "/workflow/", "health": "healthy"},
                {"key": "wiki", "label": "Wiki", "url": "https://unconfirmed.example.test/wiki/", "health": "unknown"},
            ],
            services_source=services_source,
            platform_origin="",
            **page_context,
        )

    def test_shell_uses_one_navigation_and_one_movable_profession_control(self):
        html = self.render_shell(
            [
                {"id": "one", "name": "<script>same</script>", "theme_icon": "terminal", "theme_color": "#2563eb"},
                {"id": "two", "name": "<script>same</script>", "theme_icon": "terminal", "theme_color": "#2563eb"},
            ]
        )
        elements = Elements(html).elements
        selects = [attrs for tag, attrs in elements if tag == "select" and "data-namespace-selector" in attrs]
        self.assertEqual([item["id"] for item in selects], ["namespaceSelector"])
        self.assertEqual(sum("data-base-navigation-content" in attrs for _, attrs in elements), 1)
        self.assertEqual(sum("data-base-navigation-slot" in attrs for _, attrs in elements), 1)
        self.assertEqual(sum("data-base-responsive-context" in attrs for _, attrs in elements), 1)
        self.assertEqual(sum(tag == "dialog" and "data-base-drawer" in attrs for tag, attrs in elements), 1)
        self.assertIn("&lt;script&gt;same&lt;/script&gt;", html)
        self.assertNotIn("syncSidebarLayout", html)
        self.assertNotIn('id="sidebarOverlay"', html)
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        wiki = next(attrs for tag, attrs in elements if tag == "a" and attrs.get("data-platform-service") == "wiki")
        self.assertNotIn("href", wiki)
        self.assertEqual(wiki["aria-disabled"], "true")

    def test_empty_catalog_reserves_context_slot_without_an_empty_selector(self):
        elements = Elements(self.render_shell([])).elements
        self.assertFalse(any(tag == "select" and "data-namespace-selector" in attrs for tag, attrs in elements))
        self.assertEqual(sum("data-base-responsive-context" in attrs for _, attrs in elements), 1)
        main = next(attrs for tag, attrs in elements if tag == "main")
        self.assertEqual(main["tabindex"], "-1")
        self.assertEqual(main["aria-label"], "Project Workflow")

    def test_page_header_optional_leading_keeps_title_and_default_shape(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        template = environment.from_string(
            '{% import "base/macros.html" as ui %}'
            "{{ ui.page_header(title, leading=leading) }}"
        )
        plain = template.render(title="Project <title>", leading=None)
        decorated = template.render(title="Project <title>", leading="<prefix>")
        self.assertNotIn('class="base-page-heading"', plain)
        self.assertIn('class="base-page-heading"', decorated)
        self.assertIn("&lt;prefix&gt;", decorated)
        for html in [plain, decorated]:
            self.assertEqual(sum(tag == "h1" for tag, _ in Elements(html).elements), 1)
            self.assertIn('<h1 class="base-page-title">Project &lt;title&gt;</h1>', html)
        self.assertIn('class="base-page-heading">0<h1', template.render(title="Title", leading=0))

    def test_section_header_macro_keeps_semantic_levels_zero_and_escaped_labels(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.section_header(title, heading_id='records', context=0, actions=0) }}
        {{ ui.section_header('Details', heading_id='details', level=3) }}
        {{ ui.section_header('Bounded', heading_id='bounded', level=unsafe_level) }}
        """).render(title="<img>Records</img>", unsafe_level="script")
        headings = [(tag, attrs) for tag, attrs in Elements(html).elements if tag in ["h1", "h2", "h3"]]
        self.assertEqual([(tag, attrs["id"]) for tag, attrs in headings],
                         [("h2", "records"), ("h3", "details"), ("h2", "bounded")])
        self.assertIn('class="base-section-context">0</div>', html)
        self.assertIn('class="base-action-group base-page-actions" data-align="start">0</div>', html)
        self.assertIn("&lt;img&gt;Records&lt;/img&gt;", html)
        self.assertFalse(any(tag in ["img", "script"] for tag, _ in Elements(html).elements))

    def test_code_block_macro_is_literal_focusable_and_keeps_zero_and_wrap_mode(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.code_block(value, id='command', label='Command', wrap=false) }}
        {{ ui.code_block(0, id='zero', labelled_by='title') }}
        """).render(value='  cli --name "<value>"\n\tend  ')
        blocks = {attrs["id"]: attrs for tag, attrs in Elements(html).elements if tag == "pre"}
        self.assertEqual(blocks["command"]["role"], "region")
        self.assertEqual(blocks["command"]["tabindex"], "0")
        self.assertEqual(blocks["command"]["data-wrap"], "false")
        self.assertEqual(blocks["command"]["aria-label"], "Command")
        self.assertEqual(blocks["zero"]["data-wrap"], "true")
        self.assertEqual(blocks["zero"]["aria-labelledby"], "title")
        self.assertNotIn("aria-label", blocks["zero"])
        self.assertIn("<code>0</code>", html)
        self.assertIn("<code>  cli --name &#34;&lt;value&gt;&#34;\n\tend  </code>", html)

    def test_cli_reference_uses_shared_cards_code_table_and_section_headings(self):
        html = self.render_shell(
            [], template="settings.html", commands=[dict(name="step <unsafe>", usage="cli step",
                summary="A <summary>", options=[dict(flags="--key <value>", help="Help <unsafe>",
                                                     required=True, default=0)])],
        )
        elements = Elements(html).elements
        frame = next(attrs for _, attrs in elements if "data-page-layout" in attrs)
        self.assertEqual(frame["data-page-layout"], "wide")
        heading = next(attrs for tag, attrs in elements if tag == "h2" and attrs.get("id") == "cliCommand1")
        self.assertIn("base-section-title", heading["class"].split())
        block = next(attrs for tag, attrs in elements if tag == "pre" and attrs.get("id") == "cliUsage1")
        self.assertIn("base-code-block", block["class"].split())
        self.assertEqual(block["data-wrap"], "false")
        table = next(attrs for tag, attrs in elements if tag == "table")
        self.assertIn("base-table", table["class"].split())
        self.assertIn("Help &lt;unsafe&gt;", html)
        self.assertIn("по умолчанию: 0", html)
        self.assertNotIn(".cli-command{", html)
        self.assertNotIn(".cli-usage{", html)
        self.assertNotIn(".cli-option{", html)

    def test_cli_copy_uses_base_control_and_retains_escaped_source(self):
        html = self.render_shell(
            [],
            template="settings.html",
            commands=[
                {
                    "name": "step <unsafe>",
                    "usage": '  cli --name "<value>"\n  ',
                    "summary": "CLI usage",
                    "options": [],
                }
            ],
        )
        elements = Elements(html).elements
        buttons = [attrs for tag, attrs in elements if tag == "button" and "data-base-copy-target" in attrs]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["data-base-copy-target"], "cliUsage1")
        self.assertEqual(buttons[0]["type"], "button")
        self.assertEqual(buttons[0]["aria-label"], "Копировать команду step <unsafe>")
        self.assertNotIn("onclick", buttons[0])
        self.assertIn('data-base-copy-error role="alert"', html)
        self.assertIn('data-base-copy-status role="status"', html)
        self.assertIn("  cli --name &#34;&lt;value&gt;&#34;\n  </code>", html)
        self.assertNotIn("fallbackCopyCliUsage", html)
        self.assertNotIn("function copyCliUsage", html)
        self.assertNotIn("execCommand", html)
        self.assertIn("window.PdlcClipboard = {initCopyButton, refreshCopyButton, destroyCopyButton}", html)
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_runtime_links_are_not_filtered_by_health_or_guessed_from_labels(self):
        services = [
            {"key": "project-workflow", "label": "Same", "url": "https://unused.invalid", "health": "healthy"},
            {"key": "wiki", "label": "Same", "url": "https://wiki.example.test/wiki/", "health": "unreachable"},
        ]
        html = self.render_shell([], services_source="runtime", other_services=services)
        elements = Elements(html).elements
        links = {
            attrs["data-platform-service"]: attrs
            for tag, attrs in elements
            if tag == "a" and "data-platform-service" in attrs
        }
        self.assertEqual(links["project-workflow"]["href"], "/workflow/")
        self.assertEqual(links["wiki"]["href"], "https://wiki.example.test/wiki/")
        self.assertNotIn("aria-disabled", links["wiki"])
        self.assertEqual(sum("data-base-menu" in attrs for _, attrs in elements), 1)
        self.assertNotIn("var serviceMenu=", html)

    def test_unconfirmed_addresses_remain_disabled_and_labels_are_escaped(self):
        services = [
            {
                "key": "wiki",
                "label": '<img src=x onerror="bad()">',
                "url": "https://wiki.example.test/",
                "health": "healthy",
            }
        ]
        for source in ["fallback-unreachable", "saved", ""]:
            with self.subTest(source=source):
                html = self.render_shell([], services_source=source, other_services=services)
                link = next(
                    attrs
                    for tag, attrs in Elements(html).elements
                    if tag == "a" and attrs.get("data-platform-service") == "wiki"
                )
                self.assertNotIn("href", link)
                self.assertEqual(link["aria-disabled"], "true")
                self.assertIn("&lt;img", html)
                self.assertNotIn('<img src=x onerror="bad()">', html)

    def test_namespace_states_distinguish_empty_catalog_selection_and_editable_first_form(self):
        namespace = dict(id=73, name="Owner <name>", description="Owner <description>",
                         cli_command="owner-73", theme_icon="terminal", theme_color="#123456", task_count=0)
        for items, selected, admin, message in [
            ([], None, False, "Пока ничего не создано."),
            ([namespace], None, False, "Выберите профессию для просмотра."),
            ([namespace], namespace, False, None),
            ([], None, True, None),
        ]:
            with self.subTest(count=len(items), selected=bool(selected), admin=admin):
                html = self.render_shell(
                    items, template="namespaces.html", create_mode=False,
                    selected_namespace=selected, edited_namespace=selected,
                    can_administer=admin, project_icon_options=[], default_project_icon="terminal",
                    project_icon_path=lambda icon: "M1 2",
                )
                elements = Elements(html).elements
                states = [attrs for _, attrs in elements if attrs.get("data-page-state") == "empty"]
                self.assertEqual(len(states), int(message is not None))
                if message:
                    self.assertIn(message, html)
                    self.assertEqual(states[0]["role"], "status")
                    self.assertIn("base-empty-state", states[0]["class"].split())
                forms = [attrs for tag, attrs in elements if tag == "form" and attrs.get("id") == "namespaceForm"]
                self.assertEqual(len(forms), int(admin))
                if selected:
                    self.assertIn('id="professionSummary"', html)
                    self.assertIn("Owner &lt;description&gt;", html)
                self.assertNotIn("empty-note", html)
                self.assertNotIn("nav.appendChild(empty)", html)
                if admin:
                    self.assertIn("setNamespaceFormMode('create');", html)
                    self.assertIn("document.getElementById('namespaceName').focus();", html)

    def test_namespace_form_preserves_names_patterns_help_and_values_with_base_fields(self):
        html = self.render_shell(
            [],
            template="namespaces.html",
            create_mode=True,
            selected_namespace=None,
            edited_namespace=None,
            project_icon_options=[],
            default_project_icon="terminal",
        )
        elements = Elements(html).elements
        fields = {attrs.get("id"): attrs for tag, attrs in elements if tag in ["input", "textarea"]}
        cli = fields["namespaceCliCommand"]
        self.assertIn("base-input", cli["class"].split())
        self.assertIn("required", cli)
        self.assertEqual(cli["name"], "namespaceCliCommand")
        self.assertEqual(cli["minlength"], "2")
        self.assertEqual(cli["maxlength"], "64")
        self.assertEqual(cli["pattern"], r"[a-z][a-z0-9_\-]{1,63}")
        self.assertEqual(cli["aria-describedby"], "namespaceCliHelp")
        self.assertIn('id="namespaceCliHelp"', html)
        self.assertEqual(fields["namespaceDescription"]["rows"], "2")
        self.assertIn("base-textarea", fields["namespaceDescription"]["class"].split())
        color = fields["namespaceThemeColor"]
        self.assertEqual(color["type"], "color")
        self.assertEqual(color["name"], "namespaceThemeColor")
        self.assertEqual(color["value"], "#5E6AD2")
        self.assertEqual(color["aria-label"], "Цвет")
        self.assertEqual(color["oninput"], "updateNamespaceThemePreview()")
        self.assertEqual(set(color["class"].split()), {"base-control", "base-input"})
        self.assertNotIn("theme-color-input", html)
        for field_id in ["namespaceThemeIcon", "namespaceThemeColor"]:
            labels = [attrs for tag, attrs in elements if tag == "label" and attrs.get("for") == field_id]
            self.assertEqual(len(labels), 1)
            self.assertIn("base-label", labels[0]["class"].split())
            self.assertNotIn("sr-only", labels[0]["class"].split())
        self.assertNotIn("Иконка и цвет", html)
        appearance = next(attrs for _, attrs in elements if attrs.get("id") == "namespaceThemeControls")
        self.assertEqual(appearance["role"], "group")
        self.assertEqual(appearance["aria-label"], "Оформление профессии")
        self.assertNotIn("namespaceLaunchProfile", html)
        self.assertNotIn("Профиль запуска агента", html)
        self.assertNotIn("Настройки выполнения", html)
        self.assertNotIn("Ключ запуска", html)
        self.assertNotIn("profession-execution-settings", html)
        self.assertNotIn(".label{", html)
        self.assertNotIn("input,textarea{", html)

    def test_namespace_form_does_not_expose_or_write_a_profession_launch_profile(self):
        for profile in [None, "runner-profile-73"]:
            with self.subTest(profile=profile):
                namespace = dict(id=73, name="Owner", description="", cli_command="owner-73",
                                 theme_icon="terminal", theme_color="#123456", task_count=0,
                                 launch_profile=profile)
                html = self.render_shell(
                    [namespace], template="namespaces.html", create_mode=False,
                    selected_namespace=namespace, edited_namespace=namespace,
                    project_icon_options=[], default_project_icon="terminal",
                    project_icon_path=lambda icon: "M1 2",
                )
                self.assertNotIn("namespaceLaunchProfile", html)
                self.assertNotIn("launch_profile:", html)
                self.assertNotIn("namespace.launch_profile", html)
                self.assertNotIn("namespaceExecutionSettings", html)
                self.assertNotIn("Профиль запуска агента", html)

    def test_namespace_actions_use_base_cards_without_changing_identity_or_create_mode(self):
        namespaces = [
            dict(id=key, name="Same <name>", cli_command=f"namespace-{key}",
                 description="", theme_icon="terminal", theme_color="#123456",
                 task_count=key, launch_profile="")
            for key in [7, 9]
        ]
        for create_mode in [False, True]:
            with self.subTest(create_mode=create_mode):
                html = self.render_shell(
                    namespaces, template="namespaces.html", create_mode=create_mode,
                    selected_namespace=namespaces[1],
                    edited_namespace=None if create_mode else namespaces[1],
                    project_icon_options=[], default_project_icon="terminal",
                    project_icon_path=lambda icon: "M1 2",
                )
                buttons = [attrs for tag, attrs in Elements(html).elements
                           if tag == "button" and "data-namespace-id" in attrs]
                self.assertEqual([item["data-namespace-id"] for item in buttons], ["7", "9"])
                self.assertEqual([item["aria-pressed"] for item in buttons],
                                 ["false", "false" if create_mode else "true"])
                for item in buttons:
                    self.assertIn("base-card", item["class"].split())
                    self.assertEqual(item["type"], "button")
                    self.assertEqual(item["aria-controls"], "namespaceForm")
                    self.assertEqual(item["onclick"], f"selectNamespace({item['data-namespace-id']})")
                self.assertIn("Same &lt;name&gt;", html)
                self.assertNotIn(".namespace-nav-item.active", html)
                create_links = [attrs for tag, attrs in Elements(html).elements
                                if tag == "a" and attrs.get("id") == "namespaceCreateLink"]
                self.assertEqual(len(create_links), 0 if create_mode else 1)
                if create_links:
                    self.assertEqual(create_links[0]["href"], "/workflow/namespaces/new?profession_id=9")
                    self.assertEqual(create_links[0]["aria-label"], "Создать профессию")
                    self.assertIn("base-button", create_links[0]["class"].split())
                    self.assertNotIn("type", create_links[0])

    def test_workflow_form_preserves_required_name_and_explicit_description_height(self):
        html = self.render_shell(
            [],
            template="workflows.html",
            workflows=[],
            selected_workflow=None,
            selected_workflow_id=None,
            modes=[],
            selected_mode_id=None,
            phases=[],
            phase_count=0,
            phase_blocks=[],
        )
        elements = Elements(html).elements
        name = next(attrs for tag, attrs in elements if tag == "input" and attrs.get("id") == "workflowName")
        description = next(
            attrs for tag, attrs in elements if tag == "textarea" and attrs.get("id") == "workflowDescription"
        )
        self.assertEqual(name["name"], "workflowName")
        self.assertIn("required", name)
        self.assertIn("base-input", name["class"].split())
        self.assertEqual(description["rows"], "2")
        self.assertIn("workflow-description", description["class"].split())
        self.assertIn("base-textarea", description["class"].split())
        self.assertIn(".workflow-description{min-height:64px}", html)

    def test_page_titles_use_one_base_heading_without_product_mobile_substitutions(self):
        task_key = "PROJECT-123456789012345678901234567890-<escaped>"
        cases = [
            ("tasks.html", "Задачи воркфлоу", dict(tasks=[])),
            ("phase_detail.html", "Детали фазы", None),
            ("task_detail.html", task_key, dict(
                task=dict(task_key=task_key, status="active", namespace_id=73),
                progress_done=0, progress_total=0, cycles_done=0, cycles_total=0,
            )),
        ]
        for template, title, context in cases:
            with self.subTest(template=template):
                html = (self.render_instruction_editor(template=template) if context is None
                        else self.render_shell([], template=template, **context))
                headings = re.findall(r'<h1 class="base-page-title">(.*?)</h1>', html)
                self.assertEqual(headings, [escape(title)])
                elements = Elements(html).elements
                self.assertEqual(sum(tag == "h1" for tag, _ in elements), 1)
                for retired in ["tasks-mobile-title", "tasks-desktop-title", "task-detail-mobile-title",
                                "task-detail-desktop-title", "phase-detail-mobile-title", "phase-detail-desktop-title"]:
                    self.assertNotIn(retired, html)
                if template == "task_detail.html":
                    links = [attrs for tag, attrs in elements if tag == "a"
                             and attrs.get("href") == "/workflow/tasks?profession_id=73"]
                    self.assertEqual(len(links), 1)
                    self.assertIn("base-button", links[0]["class"].split())

    def test_task_table_uses_base_scroll_and_preserves_mobile_cards(self):
        html = self.render_shell([], template="tasks.html", tasks=[])
        elements = Elements(html).elements
        table = next(attrs for tag, attrs in elements if tag == "table")
        self.assertEqual(table["aria-label"], "Задачи воркфлоу")
        self.assertEqual(set(table["class"].split()), {"base-table", "tasks-table"})
        self.assertEqual(sum(tag == "th" for tag, _ in elements), 9)
        self.assertTrue(any("base-table-scroll" in attrs.get("class", "").split() for _, attrs in elements))
        self.assertIn(".tasks-table-wrap{display:none}", html)
        self.assertIn('class="table-card-list"', html)

    def test_base_field_macros_escape_content_and_keep_accessible_error_links(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {% call ui.field('unsafe', '<label>', required=true, error=message) %}
        {{ ui.input_control('unsafe', 'name', value=value, required=true, error=true, described_by='extra-help') }}
        {% endcall %}""").render(message="<script>unsafe()</script>", value='" onfocus="unsafe()')
        elements = Elements(html).elements
        control = next(attrs for tag, attrs in elements if tag == "input")
        self.assertEqual(control["value"], '" onfocus="unsafe()')
        self.assertNotIn("onfocus", control)
        self.assertEqual(control["aria-describedby"], "unsafe-error extra-help")
        self.assertEqual(control["aria-invalid"], "true")
        error = next(attrs for _, attrs in elements if attrs.get("id") == "unsafe-error")
        self.assertEqual(error["role"], "alert")
        self.assertEqual(error["class"], "base-notice")
        self.assertEqual(error["data-appearance"], "inline")
        self.assertTrue(any(tag == "svg" for tag, _ in elements))
        self.assertFalse(any(tag == "script" for tag, _ in elements))
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&lt;label&gt;", html)

    def test_shared_card_composes_one_link_or_static_panel_and_escapes_content(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {% call ui.card(id='project', href=href, label='Project') %}
        {% call ui.card_header() %}{{ ui.card_title(title, level=2) }}{% endcall %}
        {% call ui.card_content() %}{{ description }}{% endcall %}
        {% endcall %}
        {% call ui.card(id='static') %}{{ ui.card_title('Static', level='invalid') }}{% endcall %}
        """).render(href='/projects/42?q="<value>"', title="<script>name</script>", description="<content>")
        elements = Elements(html).elements
        links = [attrs for tag, attrs in elements if tag == "a"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["href"], '/projects/42?q="<value>"')
        self.assertEqual(links[0]["data-interactive"], "true")
        self.assertNotIn("onclick", links[0])
        self.assertNotIn("tabindex", links[0])
        static = next(attrs for _, attrs in elements if attrs.get("id") == "static")
        self.assertNotIn("data-interactive", static)
        self.assertNotIn("tabindex", static)
        self.assertEqual(sum(tag == "h2" for tag, _ in elements), 1)
        self.assertEqual(sum(tag == "h3" for tag, _ in elements), 1)
        self.assertFalse(any(tag == "script" for tag, _ in elements))
        self.assertIn("&lt;content&gt;", html)

    def test_process_forms_preserve_native_roots_and_use_shared_card_styles(self):
        namespace_html = self.render_shell(
            [],
            template="namespaces.html",
            create_mode=True,
            selected_namespace=None,
            edited_namespace=None,
            project_icon_options=[],
            default_project_icon="terminal",
        )
        workflow_html = self.render_shell(
            [],
            template="workflows.html",
            phases=[],
            phase_count=0,
            phase_blocks=[],
            workflows=[],
            modes=[],
            selected_workflow=None,
            selected_workflow_id=None,
            selected_mode=None,
            selected_mode_id=None,
        )
        for html, form_id in [(namespace_html, "namespaceForm"), (workflow_html, "workflowForm")]:
            elements = Elements(html).elements
            forms = [attrs for tag, attrs in elements if tag == "form" and attrs.get("id") == form_id]
            self.assertEqual(len(forms), 1)
            self.assertTrue({"base-card", "base-card-content", "form-stack"} <= set(forms[0]["class"].split()))
            self.assertIn("data-platform-draft", forms[0])
            self.assertIn("submit", forms[0]["onsubmit"])
            self.assertNotIn(".card{", html)
            self.assertNotIn(".card-value{", html)

    def test_progress_macro_matches_bounded_values_and_does_not_invent_unknown_zero(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        macro = environment.from_string(
            "{% import 'base/macros.html' as ui %}"
            "{{ ui.progress(value, max=maximum, label='Объём', value_text='Единицы продукта') }}"
        )
        cases = [
            (0, 10, "0"),
            (3, 10, "3"),
            (-3, 10, "0"),
            (12, 10, "10"),
            (0, 0, None),
            (2, -1, None),
            (float("nan"), 10, None),
            (float("inf"), 10, None),
            (2, float("inf"), None),
        ]
        for value, maximum, expected in cases:
            with self.subTest(value=value, maximum=maximum):
                elements = Elements(macro.render(value=value, maximum=maximum)).elements
                progress = next(attrs for _, attrs in elements if attrs.get("role") == "progressbar")
                self.assertEqual(progress.get("aria-valuenow"), expected)
                self.assertEqual(progress.get("aria-valuemax"), str(maximum) if expected is not None else None)
                self.assertEqual(progress["aria-label"], "Объём")
                self.assertEqual(progress["aria-valuetext"], "Единицы продукта")
                fill = next(attrs for _, attrs in elements if attrs.get("class") == "base-progress-fill")
                self.assertNotIn("nan", fill["style"].lower())
                self.assertNotIn("inf", fill["style"].lower())
                self.assertEqual(progress.get("data-unknown"), "true" if expected is None else None)

    def test_task_badges_and_progress_keep_domain_labels_and_data(self):
        tasks = []
        for key, status, verdict, label, completed, total in [
            ("TASK-1", "done", "pass", "Проверено", 3, 3),
            ("TASK-2", "blocked", "blocked", "Нужно исправить", 0, 4),
            ("TASK-3", "active", "partial", "Есть ограничения", 0, 0),
        ]:
            tasks.append(
                dict(
                    task_key=key,
                    status=status,
                    latest_verdict=verdict,
                    latest_verdict_label=label,
                    latest_verdict_phase="Review",
                    completed=completed,
                    total_phases=total,
                    namespace_id=7,
                    namespace_theme_color="#123456",
                    namespace_theme_icon="terminal",
                    namespace_cli_command="workflow-qa",
                    namespace_name="QA",
                    workflow_name="Delivery",
                    title="Предметная задача",
                    current_phase_name="Review",
                    created_at="2026-10-22",
                )
            )
        html = self.render_shell([], template="tasks.html", tasks=tasks, project_icon_path=lambda key: "M1 2")
        elements = Elements(html).elements
        progress = [attrs for _, attrs in elements if attrs.get("role") == "progressbar"]
        self.assertEqual(len(progress), 3)
        self.assertEqual([item.get("aria-valuenow") for item in progress], ["3", "0", None])
        self.assertEqual(progress[2]["aria-valuetext"], "Фазы не заданы")
        badges = [attrs for _, attrs in elements if "base-badge" in attrs.get("class", "").split()]
        self.assertEqual(len(badges), 15)  # Three namespace labels now use the same Badge.
        semantic_badges = [item for item in badges if item["data-tone"] != "neutral"]
        self.assertEqual(len(semantic_badges), 12)
        self.assertEqual(
            [item["data-tone"] for item in semantic_badges[:6]],
            ["success", "success", "danger", "danger", "info", "warning"],
        )
        self.assertEqual(sum(attrs.get("stroke") == "#123456" for tag, attrs in elements if tag == "svg"), 3)
        for task in tasks:
            self.assertIn(task["latest_verdict_label"], html)
            self.assertEqual(html.count('data-task-key="' + task["task_key"] + '"'), 2)
            self.assertIn("/workflow/task/" + task["task_key"] + "?profession_id=7", html)
        self.assertNotIn(".status-badge{", html)
        self.assertNotIn(".bar-fill{", html)

    def test_phase_actions_use_base_disclosure_and_preserve_owner_callbacks(self):
        phases = [
            dict(id=i, phase_num=i, name="Phase <" + str(i) + ">", description="Описание", execution_type="sync")
            for i in range(1, 9)
        ]
        for count in [1, 2, 8]:
            with self.subTest(count=count):
                workflow = dict(id=3, name="Delivery", description="", phase_count=count, namespace_count=0)
                html = self.render_shell(
                    [],
                    template="workflows.html",
                    workflows=[workflow],
                    selected_workflow=workflow,
                    selected_workflow_id=3,
                    selected_namespace=None,
                    modes=[],
                    selected_mode_id=None,
                    phases=phases[:count],
                    phase_count=count,
                    phase_blocks=[dict(kind="sync", phases=[p]) for p in phases[:count]],
                )
                elements = Elements(html).elements
                picker = next(
                    attrs
                    for _, attrs in elements
                    if attrs.get("data-workflow-id") == "3" and "workflow-nav-item" in attrs.get("class", "").split()
                )
                self.assertTrue({"base-card", "base-card-content"} <= set(picker["class"].split()))
                self.assertEqual(picker["data-interactive"], "true")
                self.assertEqual(picker["aria-pressed"], "true")
                self.assertEqual(sum("base-resource-title" in attrs.get("class", "").split()
                                     for _, attrs in elements), count)
                self.assertEqual(sum("base-resource-description" in attrs.get("class", "").split()
                                     for _, attrs in elements), count)
                menus = [
                    attrs
                    for tag, attrs in elements
                    if tag == "details" and "phase-card-actions" in attrs.get("class", "").split()
                ]
                self.assertEqual(len(menus), count)
                self.assertTrue(all("data-base-menu" in menu for menu in menus))
                self.assertTrue(all(menu["data-base-menu-group"] == "phase-actions" for menu in menus))
                self.assertEqual(
                    [menu["id"] for menu in menus], ["phase-actions-" + str(i) for i in range(1, count + 1)]
                )
                items = [
                    attrs
                    for tag, attrs in elements
                    if tag == "button" and "base-menu-item" in attrs.get("class", "").split()
                ]
                self.assertEqual(len(items), 4 * count)
                deletes = [item for item in items if item.get("onclick") == "deletePhase(this)"]
                self.assertEqual(len(deletes), count)
                self.assertTrue(all(("disabled" in item) == (count == 1) for item in deletes))
                self.assertTrue(all(item["data-tone"] == "danger" for item in deletes))
                insertions = [
                    attrs
                    for tag, attrs in elements
                    if tag == "button" and attrs.get("onclick") == "addPhaseAfter(this)"
                ]
                self.assertEqual(len(insertions), count)
                self.assertTrue(all(item["data-size"] == "icon" for item in insertions))
                self.assertEqual([int(item["data-after-order"]) for item in insertions], list(range(1, count + 1)))
                self.assertIn("Действия фазы Phase &lt;1&gt;", html)
                self.assertNotIn(".phase-actions-menu{", html)
                self.assertNotIn(".phase-move-btn{", html)
                self.assertNotIn("const confirmationDialog=", html)
                panels = [
                    attrs for tag, attrs in elements if tag == "a" and "timeline-card" in attrs.get("class", "").split()
                ]
                self.assertEqual(len(panels), count)
                self.assertEqual(
                    [panel["href"] for panel in panels], ["/workflow/phase/" + str(i) for i in range(1, count + 1)]
                )
                for panel in panels:
                    classes = set(panel["class"].split())
                    self.assertEqual("base-card" in classes, count < 8)
                    self.assertEqual("base-resource-list-row" in classes, count >= 8)
                    self.assertEqual(panel["data-interactive"], "true")

    def test_editor_uses_base_controls_and_exact_skill_values_for_sync_and_parallel_instructions(self):
        for parallel in [False, True]:
            with self.subTest(parallel=parallel):
                html = self.render_instruction_editor(parallel=parallel)
                elements = Elements(html).elements
                skills = [attrs["data-instruction-skill"] for _, attrs in elements if "data-instruction-skill" in attrs]
                self.assertEqual(skills, ["tool×safe", '<script> "quoted"'])
                remove = [attrs for tag, attrs in elements if tag == "button" and "data-skill" in attrs]
                self.assertEqual([button["data-skill"] for button in remove], skills)
                for button in remove:
                    self.assertTrue({"base-control", "base-button"} <= set(button["class"].split()))
                    self.assertEqual(button["data-size"], "icon")
                    self.assertEqual(button["onclick"], "removeSkillFromInstruction(this)")
                toggles = [
                    attrs
                    for tag, attrs in elements
                    if tag == "button" and attrs.get("onclick") == "toggleInstructionType(this)"
                ]
                self.assertEqual(
                    [button["aria-pressed"] for button in toggles], ["false", "true" if parallel else "false"]
                )
                self.assertTrue(all("base-button" in button["class"].split() for button in toggles))
                frames = [attrs for _, attrs in elements if "timeline-parallel-group" in attrs.get("class", "").split()]
                self.assertEqual(len(frames), int(parallel))
                self.assertTrue(
                    all({"base-card", "base-card-content"} <= set(frame["class"].split()) for frame in frames)
                )
                actions = [
                    attrs
                    for tag, attrs in elements
                    if tag == "button" and attrs.get("onclick") in {"deleteItem(this)", "addCheck()", "addEvidence()"}
                ]
                self.assertEqual(len(actions), 4)
                self.assertTrue(all("base-button" in button["class"].split() for button in actions))
                self.assertIn("item.dataset.instructionSkill", html)
                self.assertNotIn("b.textContent.replace('×'", html)
                self.assertNotIn(".skill-remove-btn{", html)
                self.assertNotIn(".badge-sync", html)

    def test_instruction_list_keeps_owner_ids_and_uses_shared_selected_buttons_and_cards(self):
        for parallel in [False, True]:
            with self.subTest(parallel=parallel):
                elements = Elements(self.render_instruction_editor(parallel, "instructions.html")).elements
                rows = [attrs for _, attrs in elements if "instruction-row" in attrs.get("class", "").split()]
                self.assertEqual([row["data-instruction-id"] for row in rows], ["31", "32"])
                counters = [attrs for tag, attrs in elements if "step-num" in attrs.get("class", "").split()]
                self.assertEqual(len(counters), 2)
                self.assertTrue(all("base-badge" in item["class"].split() for item in counters))
                self.assertTrue(all(item.get("data-appearance") == "counter" for item in counters))
                toggles = [
                    attrs
                    for tag, attrs in elements
                    if tag == "button" and "type-badge" in attrs.get("class", "").split()
                ]
                self.assertEqual(
                    [button["data-execution-type"] for button in toggles], ["sync", "parallel" if parallel else "sync"]
                )
                self.assertEqual(
                    [button["aria-pressed"] for button in toggles], ["false", "true" if parallel else "false"]
                )
                self.assertTrue(all(button["data-variant"] == "outline" for button in toggles))
                frames = [attrs for _, attrs in elements if "parallel-group" in attrs.get("class", "").split()]
                self.assertEqual(len(frames), int(parallel))
                self.assertTrue(all("base-card" in frame["class"].split() for frame in frames))
                for tag, button in elements:
                    if tag == "button" and button.get("onclick", "").startswith(
                        ("moveInstruction", "deleteInstruction")
                    ):
                        self.assertIn("base-button", button["class"].split())
                        self.assertEqual(button["data-size"], "icon")

    def test_badge_macro_keeps_text_and_supports_an_escaped_action_composition(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.badge(0) }}{{ ui.badge(name, 'info') }}
        {% call ui.badge(tone='info') %}{{ name }}
        {{ ui.button('×', size='icon', aria_label='Remove value') }}{% endcall %}""").render(
            name="<script>Value</script>"
        )
        elements = Elements(html).elements
        badges = [attrs for _, attrs in elements if "base-badge" in attrs.get("class", "").split()]
        self.assertEqual(len(badges), 3)
        self.assertIn(">0</span>", html)
        self.assertIn("&lt;script&gt;Value&lt;/script&gt;", html)
        self.assertFalse(any(tag == "script" for tag, _ in elements))
        button = next(attrs for tag, attrs in elements if tag == "button")
        self.assertEqual(button["aria-label"], "Remove value")
        self.assertEqual(button["type"], "button")

    def test_button_macro_keeps_old_arguments_and_exposes_named_icon_pending_state(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.button('Save', 'save', 'submit', 'primary', false, false) }}
        {{ ui.button('<icon>', id='delete', variant='danger', size='icon',
                     aria_label='Удалить ресурс', pending=true, title='Подтверждение') }}""").render()
        buttons = [attrs for tag, attrs in Elements(html).elements if tag == "button"]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["type"], "submit")
        self.assertEqual(buttons[0]["id"], "save")
        self.assertEqual(buttons[0]["data-variant"], "default")
        self.assertNotIn("disabled", buttons[0])
        self.assertEqual(buttons[1]["data-variant"], "destructive")
        self.assertEqual(buttons[1]["data-size"], "icon")
        self.assertEqual(buttons[1]["aria-label"], "Удалить ресурс")
        self.assertEqual(buttons[1]["aria-busy"], "true")
        self.assertIn("disabled", buttons[1])
        self.assertNotIn("onclick", buttons[1])
        self.assertIn("&lt;icon&gt;", html)

    def test_product_feedback_uses_the_shared_native_toaster_without_a_local_timer_or_skin(self):
        html = self.render_shell([])
        elements = Elements(html).elements
        hosts = [attrs for tag, attrs in elements if "data-base-toaster" in attrs]
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["id"], "base-toaster")
        self.assertEqual(hosts[0]["aria-label"], "Уведомления")
        self.assertTrue(
            any(attrs.get("role") == "status" and "data-base-toast-status" in attrs for _, attrs in elements)
        )
        self.assertTrue(any(attrs.get("role") == "alert" and "data-base-toast-alert" in attrs for _, attrs in elements))
        self.assertIn("return window.PdlcBaseUI.notify(msg, {type: type || 'normal'});", html)
        self.assertIn("showToast('Не удалось связаться с сервером','error');", html)
        self.assertNotIn("_hideTimer", html)
        self.assertNotIn(".toast{", html)
        self.assertFalse(any(attrs.get("id") == "toast" for _, attrs in elements))

    def test_resource_macros_preserve_static_rows_and_a_single_escaped_link(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {% call ui.resource_list(id='records', density='comfortable') %}
        {% call ui.resource_list_row(id='record') %}Static{% endcall %}
        {% call ui.resource_list_row(href=href, id='linked') %}{{ name }}{% endcall %}
        {% endcall %}""").render(href="/projects/1?q=<value>", name="<script>Project</script>")
        elements = Elements(html).elements
        root = next(attrs for _, attrs in elements if attrs.get("id") == "records")
        self.assertEqual(root["data-density"], "comfortable")
        self.assertNotIn("role", root)
        static = next(attrs for _, attrs in elements if attrs.get("id") == "record")
        self.assertNotIn("tabindex", static)
        self.assertNotIn("data-interactive", static)
        links = [attrs for tag, attrs in elements if tag == "a"]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["href"], "/projects/1?q=<value>")
        self.assertEqual(links[0]["data-interactive"], "true")
        self.assertNotIn("onclick", links[0])
        self.assertFalse(any(tag == "script" for tag, _ in elements))

    def test_search_macro_preserves_native_attributes_without_product_callbacks(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.search_input('query', 'q', value=value, required=true, maxlength=120,
                           described_by='query-context', aria_label='Find resource', error='Invalid') }}
        """).render(value='<script>search</script>')
        elements = Elements(html).elements
        fields = [attrs for tag, attrs in elements if tag == "input"]
        self.assertEqual(len(fields), 1)
        field = fields[0]
        self.assertEqual(field["id"], "query")
        self.assertEqual(field["name"], "q")
        self.assertEqual(field["type"], "search")
        self.assertEqual(field["value"], '<script>search</script>')
        self.assertEqual(field["aria-label"], "Find resource")
        self.assertEqual(field["aria-describedby"], "query-error query-context")
        self.assertEqual(field["aria-invalid"], "true")
        self.assertEqual(field["maxlength"], "120")
        self.assertIn("required", field)
        self.assertFalse(any(name.startswith("on") for name in field))
        self.assertFalse(any(tag in ["script", "button"] for tag, _ in elements))
        icon = next(attrs for tag, attrs in elements if tag == "svg")
        self.assertEqual(icon["aria-hidden"], "true")

    def test_resource_action_macro_is_a_native_button_with_explicit_selection_and_escaping(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.resource_list_button(label, pressed=true, id='chosen') }}
        {{ ui.resource_list_button('Unavailable', disabled=true, id='locked') }}
        """).render(label="<script>Unsafe</script>")
        buttons = {attrs["id"]: attrs for tag, attrs in Elements(html).elements if tag == "button"}
        self.assertEqual(buttons["chosen"]["type"], "button")
        self.assertEqual(buttons["chosen"]["aria-pressed"], "true")
        self.assertIn("disabled", buttons["locked"])
        self.assertNotIn("aria-pressed", buttons["locked"])
        self.assertIn("base-resource-list-row", buttons["chosen"]["class"].split())
        self.assertIn("&lt;script&gt;Unsafe&lt;/script&gt;", html)
        self.assertFalse(any(tag == "script" for tag, _ in Elements(html).elements))

    def test_editors_use_shared_autosize_without_local_geometry_or_duplicate_input_handlers(self):
        for template, fields in [("phase_detail.html", 4), ("instructions.html", 2)]:
            html = self.render_instruction_editor(parallel=True, template=template)
            elements = Elements(html).elements
            areas = [attrs for tag, attrs in elements if tag == "textarea"]
            self.assertGreaterEqual(len(areas), fields)
            self.assertTrue(all("data-base-autosize" in attrs for attrs in areas))
            self.assertTrue(all(attrs["rows"] == "1" for attrs in areas))
            self.assertIn(
                "window.PdlcTextarea = {initTextareaAutosize, refreshTextareaAutosize, destroyTextareaAutosize}", html
            )
            self.assertNotIn("resizeInlineTextarea", html)
            self.assertNotIn("resizeInstructionTextarea", html)
            self.assertIn("destroyTextareaAutosize", html)
            self.assertIn("data-original-description=", html)
        phase = self.render_instruction_editor()
        self.assertIn("window.PdlcTextarea.initTextareaAutosize(li.querySelector('textarea'));", phase)
        self.assertIn("window.PdlcTextarea.refreshTextareaAutosize(input);", phase)
        self.assertIn("instructionDraft(event.target).edit();", phase)

    def test_textarea_macro_keeps_default_sizing_and_explicit_autosize_opt_in(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {{ ui.textarea_control('regular', 'plain', value=value, rows=7, required=true) }}
        {{ ui.textarea_control('growing', 'sized', value=value, rows=1,
                               appearance='inline', autosize=true) }}""").render(value="<script>Exact</script>")
        fields = {attrs["id"]: attrs for tag, attrs in Elements(html).elements if tag == "textarea"}
        self.assertNotIn("data-base-autosize", fields["regular"])
        self.assertEqual(fields["regular"]["rows"], "7")
        self.assertIn("required", fields["regular"])
        self.assertIn("data-base-autosize", fields["growing"])
        self.assertEqual(fields["growing"]["rows"], "1")
        self.assertIn("&lt;script&gt;Exact&lt;/script&gt;", html)

    def test_phase_outline_uses_shared_section_navigation_and_retains_product_hash_history(self):
        html = self.render_instruction_editor()
        elements = Elements(html).elements
        labels = [attrs for tag, attrs in elements if tag == "label" and attrs.get("for") == "phaseSectionSelect"]
        self.assertEqual(len(labels), 1)
        self.assertIn("base-visually-hidden", labels[0]["class"].split())
        self.assertIn("Раздел редактора", html)
        nav = next(
            attrs for tag, attrs in elements if tag == "nav" and attrs.get("aria-labelledby") == "phase-outline-title"
        )
        self.assertIn("base-section-navigation", nav["class"].split())
        self.assertEqual(nav["data-orientation"], "vertical")
        links = [
            attrs
            for tag, attrs in elements
            if tag == "a" and "base-section-navigation-item" in attrs.get("class", "").split()
        ]
        self.assertEqual(
            [link["href"] for link in links],
            ["#phase-overview", "#phase-instructions", "#phase-checks", "#phase-evidence"],
        )
        self.assertEqual(links[0]["aria-current"], "location")
        self.assertTrue(all("aria-current" not in link for link in links[1:]))
        self.assertNotIn(".phase-outline-link", html)
        self.assertNotIn(".phase-outline-list", html)
        self.assertIn("link.hash.slice(1)", html)
        self.assertIn("phaseSectionNavigationLock = sectionId;", html)
        self.assertIn("window.PdlcPlatformNavigation.syncRoute(nextUrl, method === 'replaceState');", html)
        self.assertIn("page.on(window,'popstate', restorePhaseSectionFromLocation);", html)

    def test_section_navigation_macros_keep_native_links_and_escape_labels(self):
        templates = Path(__file__).parents[1] / "project_workflow/interfaces/ui/templates"
        environment = Environment(loader=FileSystemLoader(templates), autoescape=True)
        html = environment.from_string("""{% import 'base/macros.html' as ui %}
        {% call ui.section_navigation(label='Sections') %}
        {{ ui.section_navigation_item(href, label=name, active=true) }}
        {{ ui.section_navigation_item('#plain', label='Plain') }}
        {% endcall %}
        {% call ui.section_navigation(orientation='vertical', labelled_by='outline') %}
        {% call ui.section_navigation_item('#checks', active=true, current='location') %}
        <span>{{ name }}</span>{{ ui.badge(0, 'muted', 'inline') }}{% endcall %}
        {% endcall %}""").render(href="/path?q=<value>", name="<script>Title</script>")
        elements = Elements(html).elements
        navs = [attrs for tag, attrs in elements if tag == "nav"]
        links = [attrs for tag, attrs in elements if tag == "a"]
        self.assertEqual(navs[0]["data-orientation"], "horizontal")
        self.assertEqual(navs[1]["data-orientation"], "vertical")
        self.assertEqual(navs[1]["aria-labelledby"], "outline")
        self.assertEqual(links[0]["href"], "/path?q=<value>")
        self.assertEqual(links[0]["aria-current"], "page")
        self.assertNotIn("aria-current", links[1])
        self.assertEqual(links[2]["aria-current"], "location")
        self.assertIn("&lt;script&gt;Title&lt;/script&gt;", html)
        self.assertFalse(any(tag == "script" for tag, _ in elements))
