"""Download the public help-center pages (same sources as Experiment 6) into knowledge_base.txt.

Run:  python fetch_knowledge_base.py
"""
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUTPUT_FILE = Path(__file__).parent / "knowledge_base.txt"
SECTION_SEPARATOR = "=====PAGE====="
MIN_PAGE_CHARS = 300
MAX_PAGE_CHARS = 6000
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]

PAGES_BY_TOPIC = {
    "Order Tracking": [
        "https://www.shipaid.com/blog/how-do-i-track-my-order-on-shopify-a-comprehensive-guide-for-e-commerce-merchants",
        "https://www.eesel.ai/blog/ecommerce-faq-examples",
    ],
    "Returns and Refunds": [
        "https://usource.me/top-20-most-commonly-asked-ecommerce-customer-service-queries/",
    ],
    "Account Access": [
        "https://support.microsoft.com/en-us/help/4026971/microsoft-account-how-to-reset-your-password",
        "https://www.fittingbox.com/en/resources/help-center/how-do-i-change-my-password",
    ],
    "Billing and Payments": [
        "https://help.nordlayer.com/docs/i-have-been-charged-twice.md",
        "https://help.letsdothis.com/en/articles/10546731-what-to-do-if-you-have-been-charged-twice",
        "https://help.cathopic.com/help-troubleshooting/i-was-charged-twice/",
    ],
    "Technical Support": [
        "https://support.mozilla.org/en-US/kb/websites-dont-load-troubleshoot-and-fix-errors",
    ],
}

BUILTIN_FAQ = """Order Tracking
You can follow your shipment from the Orders section of your account. Once an order has been dispatched, a tracking link appears next to it. If the tracking status has not changed for more than 48 hours, contact support and quote your order reference. The assistant cannot see live order status.

Order Cancellation
An order can be cancelled from the Orders section as long as it has not been dispatched yet. Open the order and choose Cancel Order. If the order has already shipped, it cannot be cancelled; wait for delivery and start a return instead. Refunds for cancelled orders go back to the original payment method.

Shipping Times and Costs
Standard delivery usually takes 3 to 7 business days after dispatch, and express delivery 1 to 3 business days. The shipping fee and the estimated delivery date are shown at checkout before you pay. Delivery times can be longer during sales, holidays, or for remote addresses.

Returns and Refunds
Unused items in their original packaging can be returned within 14 days of delivery. Some items are not eligible for return. To start a return, go to Orders, select the item, and click Return Request. Once the returned item is received and approved, the refund is normally issued to the original payment method within 5 to 7 business days. The assistant cannot approve refunds.

Account Access
If you are unable to sign in, click Forgot Password on the sign-in page and follow the reset link sent to your email. If the email does not arrive, look in your spam folder and make sure you typed the email address registered on your account. Never share your password or one-time verification code with anyone.

Billing and Payments
The payment status of an order is shown in its order details. If you think you were charged twice, do not try to pay again. Contact the billing support team with the transaction date and the order reference. Never share your full card number or security code.

Technical Support
If the website does not load, refresh the page, check your internet connection, and make sure your browser is up to date. If the problem continues, clear the browser cache or open the site in a private window. When contacting support, mention the exact error message and the steps that caused it. Never share passwords or verification codes.

Contact Support
For anything not covered in this FAQ, contact the support team through the Help section of the website. Give a short description of the issue and the order reference if relevant, but never send passwords, one-time codes, or full payment-card details.
"""


def scrape_text(url: str) -> str:
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
    resp.raise_for_status()
    if url.endswith(".md") or "text/plain" in resp.headers.get("Content-Type", ""):
        text = resp.text
    else:
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(NOISE_TAGS):
            tag.decompose()
        container = soup.find("article") or soup.find("main") or soup.body or soup
        text = container.get_text("\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:MAX_PAGE_CHARS]


def main():
    collected = []
    for topic, links in PAGES_BY_TOPIC.items():
        for link in links:
            try:
                page_text = scrape_text(link)
                if len(page_text) < MIN_PAGE_CHARS:
                    raise ValueError("page text too short")
                collected.append((topic, link, page_text))
                print(f"[OK]   {topic:22s} {len(page_text):5d} chars  {link}")
            except Exception as err:
                print(f"[FAIL] {topic:22s} {link} -> {err}")
    with OUTPUT_FILE.open("w", encoding="utf-8") as out:
        for topic, link, page_text in collected:
            out.write(f"{SECTION_SEPARATOR}\n{topic}\nSource: {link}\n{page_text}\n\n")
        # always append the built-in FAQ so every topic (e.g. Technical Support) is covered
        out.write(f"{SECTION_SEPARATOR}\nStore Help Center FAQ\nSource: built-in\n{BUILTIN_FAQ}")
    print(f"{OUTPUT_FILE.name} written ({len(collected)} pages + built-in FAQ)")


if __name__ == "__main__":
    main()
