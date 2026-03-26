import asyncio
import os
import pdfplumber
import json
import logging

from analyzer import analyze_resume
from cv_generator import generate_cv
from pdf_generator import markdown_to_pdf

# Mute noisy logs from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)

# Terminal Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_banner():
    print(f"{Colors.CYAN}{Colors.BOLD}")
    print("========================================")
    print("🤖   AI RESUME ANALYZER & CV BOT   🤖")
    print("========================================")
    print(f"{Colors.ENDC}")

def get_multiline_input(prompt: str) -> str:
    print(f"{Colors.BLUE}{prompt} (Type 'END' on a new line when finished):{Colors.ENDC}")
    lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == 'END':
                break
            lines.append(line)
        except EOFError:
            break
    return '\n'.join(lines)

def extract_pdf_text(filepath: str) -> str:
    if not os.path.exists(filepath):
        print(f"{Colors.FAIL}Error: File '{filepath}' not found.{Colors.ENDC}")
        return ""
    
    try:
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"{Colors.FAIL}Failed to read PDF: {e}{Colors.ENDC}")
        return ""

async def interactive_bot():
    print_banner()

    # Get Resume PDF
    print(f"{Colors.BOLD}1. Let's upload your Resume.{Colors.ENDC}")
    resume_path = input(f"{Colors.CYAN}Enter the absolute path to your PDF resume (e.g., C:/resume.pdf): {Colors.ENDC}").strip().strip('"')
    
    resume_text = extract_pdf_text(resume_path)
    if not resume_text:
        return
    print(f"{Colors.GREEN}✅ Resume extracted successfully ({len(resume_text)} characters).{Colors.ENDC}\n")

    # Get JD
    print(f"{Colors.BOLD}2. Now, paste the Job Description.{Colors.ENDC}")
    jd_text = get_multiline_input(f"{Colors.CYAN}Job Description")
    if not jd_text.strip():
        print(f"{Colors.FAIL}Error: Job Description cannot be empty.{Colors.ENDC}")
        return
    print(f"{Colors.GREEN}✅ Job Description received ({len(jd_text)} characters).{Colors.ENDC}\n")

    # Analyze
    print(f"{Colors.WARNING}⏳ Analyzing resume against JD... Please wait (this may take a minute).{Colors.ENDC}")
    try:
        results = await analyze_resume(jd_text, resume_text)
    except Exception as e:
        print(f"{Colors.FAIL}Analysis failed: {e}{Colors.ENDC}")
        return

    # Print Results
    print("\n" + "="*40)
    print(f"{Colors.HEADER}{Colors.BOLD}📊 ANALYSIS RESULTS{Colors.ENDC}")
    print("="*40)
    
    score = results.get('match_score', 0)
    score_color = Colors.GREEN if score >= 70 else (Colors.WARNING if score >= 40 else Colors.FAIL)
    print(f"\n{Colors.BOLD}Overall Match Score:{Colors.ENDC} {score_color}{score}/100{Colors.ENDC}")
    print(f"{Colors.BOLD}Summary:{Colors.ENDC}\n{results.get('summary', '')}")
    
    print(f"\n{Colors.BOLD}🔍 Missing Skills (Gaps):{Colors.ENDC}")
    gaps = results.get('gap_analysis', [])
    if gaps:
        for g in gaps:
            print(f"  {Colors.FAIL}✗{Colors.ENDC} {g}")
    else:
        print(f"  {Colors.GREEN}✓ No critical missing skills found!{Colors.ENDC}")

    print(f"\n{Colors.BOLD}⚠️ Weaknesses / Negative Points:{Colors.ENDC}")
    negatives = results.get('negative_points', [])
    if negatives:
        for n in negatives:
            sev_color = Colors.FAIL if n.get('severity') == 'critical' else Colors.WARNING
            print(f"  [{sev_color}{n.get('severity', 'moderate').upper()}{Colors.ENDC}] {n.get('issue', '')}")
            print(f"      → {Colors.CYAN}Fix:{Colors.ENDC} {n.get('recommendation', '')}")
    else:
        print(f"  {Colors.GREEN}✓ No major weaknesses identified.{Colors.ENDC}")

    print("\n" + "="*40)

    # Ask for CV Generation
    ans = input(f"\n{Colors.GREEN}Do you want me to generate an optimized CV targeted for this JD? (y/n): {Colors.ENDC}").strip().lower()
    
    if ans == 'y':
        print(f"\n{Colors.WARNING}⏳ Generating optimized CV using STAR method... Please wait.{Colors.ENDC}")
        try:
            cv_markdown = await generate_cv(
                jd_text=jd_text,
                resume_text=resume_text,
                analysis_results=results
            )
            
            # Save Markdown
            md_filename = "optimized_cv.md"
            with open(md_filename, "w", encoding="utf-8") as f:
                f.write(cv_markdown)
            print(f"{Colors.GREEN}✅ Markdown CV saved directly to: {os.path.abspath(md_filename)}{Colors.ENDC}")

            # Generate PDF
            print(f"{Colors.WARNING}⏳ Converting to professional PDF...{Colors.ENDC}")
            pdf_bytes = markdown_to_pdf(cv_markdown)
            pdf_filename = "Optimized_Resume.pdf"
            with open(pdf_filename, "wb") as f:
                f.write(pdf_bytes)
            print(f"{Colors.GREEN}✅ PDF CV successfully generated and saved to: {os.path.abspath(pdf_filename)}{Colors.ENDC}")

        except Exception as e:
            print(f"{Colors.FAIL}CV Generation failed: {e}{Colors.ENDC}")

    print(f"\n{Colors.BLUE}Thank you for using the AI Resume Bot! Best of luck with your application.{Colors.ENDC}")

if __name__ == "__main__":
    asyncio.run(interactive_bot())
