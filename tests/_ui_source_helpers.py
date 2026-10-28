"""Read the public controller selected by an SSR page, rather than assuming inline JS."""

import hashlib
import json
import re


def page_source(client, response):
    html = response.text
    match = re.search(r"const factory=window\.WorkflowPageControllers\[(\"[^\"]+\")\]", html)
    if not match:
        return html
    name = json.loads(match.group(1))
    urls = re.findall(r'<script\b[^>]*src="([^"]+)"', html)
    matches = [url for url in urls if url.endswith("/" + name + ".js")]
    assert len(matches) == 1
    asset = client.get(matches[0])
    assert asset.status_code == 200
    assert hashlib.sha256(asset.content).hexdigest() == matches[0].split("/")[-2]
    return html + "\n" + asset.text


def parallel_groups(html):
    """Read actual group boundaries, independent of nested cards and icons."""
    from html.parser import HTMLParser

    class Groups(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.group_depth = None
            self.groups = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "div":
                self.depth += 1
                if "timeline-parallel-group" in attributes.get("class", "").split():
                    assert self.group_depth is None
                    self.group_depth = self.depth
                    self.groups.append({"ids": [], "text": ""})
            if self.group_depth is not None and "data-phase-id" in attributes:
                self.groups[-1]["ids"].append(attributes["data-phase-id"])

        def handle_endtag(self, tag):
            if tag == "div":
                if self.depth == self.group_depth:
                    self.group_depth = None
                self.depth -= 1

        def handle_data(self, data):
            if self.group_depth is not None:
                self.groups[-1]["text"] += data

    parser = Groups()
    parser.feed(html)
    assert parser.depth == 0
    return parser.groups
