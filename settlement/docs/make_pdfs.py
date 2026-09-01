from playwright.sync_api import sync_playwright
docs = [
    ("/home/user/jewelry-cost-calculator/settlement/docs/agreement.html",
     "/home/user/jewelry-cost-calculator/settlement/static/docs/CBS-Consignment-Agreement.pdf"),
    ("/home/user/jewelry-cost-calculator/settlement/docs/how-it-works.html",
     "/home/user/jewelry-cost-calculator/settlement/static/docs/CBS-Consignment-How-It-Works.pdf"),
]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    pg = b.new_page()
    for src, dest in docs:
        pg.goto(f"file://{src}")
        pg.pdf(path=dest, format="Letter",
               margin={"top": "0.75in", "bottom": "0.75in", "left": "0.75in", "right": "0.75in"},
               display_header_footer=True,
               header_template="<span></span>",
               footer_template="<div style='font-size:8px;color:#777;width:100%;text-align:center'>Continental Bead Suppliers — Page <span class='pageNumber'></span> of <span class='totalPages'></span></div>")
        print("wrote", dest)
    b.close()
