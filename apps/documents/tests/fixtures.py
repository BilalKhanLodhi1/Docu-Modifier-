"""Small generated fixtures so tests never depend on external files."""
import io

import docx
from docx.enum.text import WD_BREAK
from docx.shared import Inches, Pt
from PIL import Image


def png_bytes(size=(320, 200), color=(40, 90, 160)):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color)
    for x in range(0, size[0], 20):
        for y in range(size[1]):
            img.putpixel((x, y), (250, 250, 250))
    img.save(buf, "PNG")
    return buf.getvalue()


def lab_report_docx(path):
    """A representative programming lab report: tasks, code, figure, table, link."""
    d = docx.Document()
    d.add_heading("Lab 3: Object Oriented Programming", level=0)
    d.add_heading("Objective", level=1)
    d.add_paragraph("the objective of this lab is to learn about classes and object in java, we will make 3 programs that uses constructors and methods.")
    d.add_heading("Task 1: Bank Account", level=1)
    d.add_paragraph("In this task we created a class BankAccount that store balance of 5000 rupees and allow deposit() and withdraw() methods.")
    for line in ["public class BankAccount {", "    private double balance = 5000; // initial balance",
                 "    public void deposit(double amt) { balance += amt; }", "}"]:
        p = d.add_paragraph()
        r = p.add_run(line)
        r.font.name = "Courier New"
        r.font.size = Pt(10)
    d.add_paragraph().add_run().add_picture(io.BytesIO(png_bytes()), width=Inches(3))
    d.add_paragraph("Figure 1: Output of the BankAccount program")
    d.add_heading("Task 2: Student Records", level=1)
    d.add_paragraph("The program reads 25 student records and calculates the average which was 72.5% in our test run on 12/10/2026.")
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Student", "Marks"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Ali", "81"
    d.add_paragraph("Results are consistent with reference [2].", style="List Bullet")
    d.add_heading("Conclusion", level=1)
    d.add_paragraph("In conclusion classes make code more organized and reuseable and this lab helped us understand it better.")
    d.save(str(path))
    return path


def simple_pdf(path, pages=5):
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Page {i + 1} heading", fontsize=18)
        page.insert_text((72, 140), f"This is body text on page {i + 1} of the sample PDF document.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def scanned_pdf(path):
    """Image-only PDF (simulates a scan)."""
    import pymupdf
    from PIL import ImageDraw
    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    draw.text((100, 100), "SCANNED INVOICE 2026", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()
    return path
