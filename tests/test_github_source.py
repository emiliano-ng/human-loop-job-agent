from app.github_source import _parse_html_tables

TABLE = """
<table>
<tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th><th>Age</th></tr>
<tr><td><strong><a href="https://acme.test">Acme</a></strong></td><td>Robotics Software Intern</td>
<td>Austin, TX</td><td><a href="https://acme.test/jobs/1"><img alt="Apply"></a></td><td>0d</td></tr>
<tr><td>↳</td><td>Firmware Intern</td><td>Remote</td>
<td><a href="https://acme.test/jobs/2">Apply</a></td><td>1d</td></tr>
<tr><td>Beta</td><td>Software Intern 🛂</td><td>NYC</td><td><a href="https://beta.test/1">Apply</a></td><td>1d</td></tr>
<tr><td>Gamma</td><td>Software Intern 🇺🇸</td><td>NYC</td><td><a href="https://gamma.test/1">Apply</a></td><td>1d</td></tr>
<tr><td>Delta</td><td>Software Intern 🔒</td><td>NYC</td><td><a href="https://delta.test/1">Apply</a></td><td>1d</td></tr>
<tr><td>Zeta</td><td>Software Intern, U.S. citizenship required</td><td>NYC</td>
<td><a href="https://zeta.test/1">Apply</a></td><td>1d</td></tr>
<tr><td>Eps</td><td>Software Intern 🎓</td><td>NYC</td><td><a href="https://eps.test/1">Apply</a></td><td>1d</td></tr>
</table>
"""


def test_parser_keeps_only_eligible_rows():
    postings = _parse_html_tables(TABLE, source="github:test/list")
    assert [(p.company, p.title) for p in postings] == [
        ("Acme", "Robotics Software Intern"),
        ("Acme", "Firmware Intern"),
        ("Eps", "Software Intern"),
    ]


def test_parser_extracts_links_and_metadata():
    postings = _parse_html_tables(TABLE, source="github:test/list")
    assert postings[0].url == "https://acme.test/jobs/1"
    assert postings[0].location == "Austin, TX"
    assert postings[0].source == "github:test/list"
    assert "advanced degree" in postings[2].description


def test_posting_ids_are_stable_and_unique():
    first = _parse_html_tables(TABLE, source="s")
    second = _parse_html_tables(TABLE, source="s")
    assert [p.posting_id for p in first] == [p.posting_id for p in second]
    assert len({p.posting_id for p in first}) == len(first)


def test_row_without_link_still_parses():
    html = "<table><tr><td>Solo</td><td>Embedded Intern</td><td>Remote</td><td>closed</td><td>1d</td></tr></table>"
    postings = _parse_html_tables(html, source="s")
    assert len(postings) == 1
    assert "no direct link" in postings[0].url
