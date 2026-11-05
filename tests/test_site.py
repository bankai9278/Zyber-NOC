"""Landing, reports and about pages read saved rows only."""

from app.database import add_device


def _seed(app):
    path = app.config["DATABASE_PATH"]
    device = add_device(path, name="Core switch", ip_address="10.0.0.2", device_type="switch")
    device_id = device["id"] if isinstance(device, dict) else device
    return path, device_id


def test_landing_page_without_devices(client):
    html = client.get("/").get_data(as_text=True)
    assert "Every device." in html
    assert "ping -n 5 &lt;saved device&gt;" in html
    assert "No checks yet" in html


def test_landing_page_counts_saved_devices(app, client):
    _seed(app)
    html = client.get("/").get_data(as_text=True)
    assert 'data-counter="1"' in html
    assert "ping -n 5 10.0.0.2" in html
    assert "Core switch" in html


def test_reports_page_without_devices(client):
    response = client.get("/reports")
    assert response.status_code == 200
    assert "No devices yet." in response.get_data(as_text=True)


def test_reports_page_lists_each_device(app, client):
    _seed(app)
    html = client.get("/reports").get_data(as_text=True)
    assert "Core switch" in html
    assert "No recoveries yet" in html
    assert "No checks yet" in html


def test_about_page_renders(client):
    response = client.get("/about")
    assert response.status_code == 200
    assert "One request, end to end." in response.get_data(as_text=True)


def test_site_pages_load_premium_assets_without_inline_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "js/premium.js" in html
    assert "css/premium.css" in html
    assert "<script>" not in html
    assert " style=" not in html


def test_about_page_tells_the_owner_story(client):
    html = client.get("/about").get_data(as_text=True)
    assert "About Zyber NOC" in html
    assert "Mohawk College" in html
    assert "Skyline Paralegal" in html
    assert "design specialist" in html
    assert "$174,171.28" in html
    assert "https://www.linkedin.com/in/yash-oza-it/" in html


def test_about_page_is_honest_about_how_it_was_built(client):
    html = client.get("/about").get_data(as_text=True)
    assert "Computer Systems Technician – Networking, 2025" in html
    assert "Built with help from AI coding tools. I planned the features, tested them, and can explain how each part works." in html
    assert "on my own" not in html
    # Built features are no longer listed as plans.
    assert "Add SNMP polling." not in html
    assert "Host a read-only demo." not in html
    # The note to add personal sentences is a template comment, never sent to visitors.
    assert "Yash: add" not in html


def test_about_page_phrases_certifications_as_goals(client):
    html = client.get("/about").get_data(as_text=True)
    assert "Work toward certifications such as the CCNA." in html


def test_about_page_shows_large_logo(client):
    html = client.get("/about").get_data(as_text=True)
    assert 'class="about-logo"' in html
    assert 'width="96"' in html


def test_logo_file_is_served(client):
    response = client.get("/static/img/logo-yo.svg")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"
    body = response.get_data(as_text=True)
    assert "Yash Oza logo" in body
    assert "#3ef0a5" in body
    response.close()


def test_logo_is_linked_in_header_footer_and_favicon(client):
    html = client.get("/").get_data(as_text=True)
    header = html.split('<header class="site-header">', 1)[1].split("</header>", 1)[0]
    footer = html.split('<footer class="site-footer">', 1)[1].split("</footer>", 1)[0]
    assert 'src="/static/img/logo-yo.svg"' in header
    assert 'alt="Yash Oza logo"' in header
    assert 'src="/static/img/logo-yo.svg"' in footer
    assert "Built by Yash Oza" in footer
    assert '<link rel="icon" type="image/svg+xml" href="/static/img/logo-yo.svg">' in html


def test_about_page_has_no_inline_script_or_style(client):
    html = client.get("/about").get_data(as_text=True)
    assert "<script>" not in html
    assert " style=" not in html
    assert "<style" not in html
