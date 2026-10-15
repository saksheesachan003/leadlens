from app.extract import extract_company, extract_emails, extract_phones, classify_email
from app.scraper import normalize_domain, Scraper


def test_normalize_domain_variants():
    assert normalize_domain("https://www.Acme.com/about?x=1") == "acme.com"
    assert normalize_domain("acme.co.uk") == "acme.co.uk"
    assert normalize_domain("jane@acme.com") == "acme.com"
    assert normalize_domain("not a website") is None
    assert normalize_domain("") is None


def test_emails_mailto_obfuscated_and_junk():
    html = '<a href="mailto:Owner@Acme.com?subject=hi">x</a><img src="logo@2x.png">'
    text = "Write to bob [at] acme [dot] com or sales@acme.com. Pixel: abc@sentry.io"
    emails = extract_emails(html, text)
    assert emails == ["owner@acme.com", "sales@acme.com", "bob@acme.com"]


def test_phones_normalized_and_deduped():
    html = '<a href="tel:+13035550142">call</a>'
    text = "Call 303.555.0142 or (720) 555-0199. Fax 1111111111"
    assert extract_phones(html, text) == ["(303) 555-0142", "(720) 555-0199"]


def test_classify_email():
    assert classify_email("info@acme.com", "acme.com") == {"email": "info@acme.com", "type": "role", "on_domain": True}
    assert classify_email("jane.doe@gmail.com", "acme.com")["on_domain"] is False


def test_company_profile_signals():
    pages = [{"url": "https://acme.com/", "html": """
      <html><head><title>Home | Acme Plumbing</title><meta name="description" content="Plumbing in Denver">
      <script src="https://www.googletagmanager.com/gtag/js"></script></head>
      <body>Family-owned plumbing and heating company since 1988. Our team of 30 employees.
      Jane Doe, Owner. jane.doe@acme.com. Home About Contact Denver, CO 80202. &copy; 2020 Acme
      <a href="https://www.linkedin.com/company/acme">in</a></body></html>"""}]
    p = extract_company(pages, "acme.com")
    assert p["company_name"] == "Acme Plumbing"
    assert p["founded_year"] == 1988
    assert p["family_or_owner_operated"] is True
    assert p["employee_hint"] == 30
    assert p["location"] == "Denver, CO"
    assert p["industry"] == "HVAC & Plumbing"
    assert p["last_site_update_year"] == 2020
    assert "Google Analytics" in p["tech_stack"]
    assert p["socials"]["linkedin"].startswith("https://www.linkedin.com")
    assert p["emails"][0] == {"email": "jane.doe@acme.com", "type": "personal", "on_domain": True,
                              "name": "Jane Doe", "title": "Owner"}


def test_name_is_never_invented_from_email():
    pages = [{"url": "https://x.com/", "html": "<p>Write to greenleaf.tom@x.com</p>"}]
    assert "name" not in extract_company(pages, "x.com")["emails"][0]


def test_link_picker_prefers_contact_and_stays_on_site():
    html = '<a href="/about">About</a><a href="/contact-us">Contact</a><a href="https://other.com/contact">x</a>'
    assert Scraper._pick_links(html, "https://acme.com/") == ["https://acme.com/contact-us", "https://acme.com/about"]
