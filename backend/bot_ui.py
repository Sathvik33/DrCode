import streamlit as st
import asyncio
import pdfplumber
import os

from analyzer import analyze_resume
from cv_generator import generate_cv
from pdf_generator import markdown_to_pdf

# Configure Streamlit page
st.set_page_config(page_title="AI Resume Bot", page_icon="🤖", layout="wide")

st.title("🤖 AI Resume Strategy Bot")
st.markdown("Upload your current resume, paste the Job Description, and let the AI instantly analyze your fit and **write a new, optimized CV** for you.")

# Initialize session state variables
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""
if "analysis_results" not in st.session_state:
    st.session_state.analysis_results = None
if "cv_markdown" not in st.session_state:
    st.session_state.cv_markdown = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None

# Sidebar for Inputs
with st.sidebar:
    st.header("1. Upload Resume")
    uploaded_file = st.file_uploader("Upload PDF Resume", type=["pdf"])
    
    if uploaded_file is not None:
        try:
            text = ""
            with pdfplumber.open(uploaded_file) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
            st.session_state.resume_text = text.strip()
            st.success(f"Resume loaded! ({len(text)} chars)")
        except Exception as e:
            st.error(f"Error reading PDF: {e}")

    st.header("2. Job Description")
    jd_text = st.text_area("Paste the Job Description here:", height=300)

    analyze_btn = st.button("🚀 Analyze Fit", use_container_width=True, type="primary")

# Main Logic
if analyze_btn:
    if not st.session_state.resume_text:
        st.warning("Please upload a resume first.")
    elif not jd_text.strip():
        st.warning("Please paste a job description.")
    else:
        with st.spinner("🧠 Analyzing your resume against the JD... (this takes a minute)"):
            try:
                # Run the async analysis pipeline
                results = asyncio.run(analyze_resume(jd_text, st.session_state.resume_text))
                st.session_state.analysis_results = results
                st.session_state.cv_markdown = None  # Reset CV on new analysis
                st.session_state.pdf_bytes = None
                st.success("Analysis Complete!")
            except Exception as e:
                st.error(f"Analysis Failed: {e}")

# Display Results
if st.session_state.analysis_results:
    res = st.session_state.analysis_results
    
    # Hero Score Metrics
    score = res.get("match_score", 0)
    col1, col2, col3 = st.columns(3)
    col1.metric("Overall Match Score", f"{score}/100")
    col2.metric("Missing Skills Identified", len(res.get("gap_analysis", [])))
    col3.metric("Critical Weaknesses", len([w for w in res.get("negative_points", []) if w.get("severity") == "critical"]))

    st.markdown("### 📋 Executive Summary")
    st.info(res.get("summary", "No summary provided."))

    # Layout for Gaps and Weaknesses
    colA, colB = st.columns(2)
    
    with colA:
        st.markdown("### 🔍 Missing Skills")
        gaps = res.get("gap_analysis", [])
        if gaps:
            for g in gaps:
                st.markdown(f"- ❌ {g}")
        else:
            st.success("No critical missing skills found!")

    with colB:
        st.markdown("### ⚠️ Critical Weaknesses")
        negatives = res.get("negative_points", [])
        if negatives:
            for n in negatives:
                st.error(f"**[{n.get('severity', 'moderate').upper()}]** {n.get('issue', '')}  \n**Fix:** {n.get('recommendation', '')}")
        else:
            st.success("No major weaknesses identified.")

    st.markdown("---")
    
    # CV Generation Section
    st.markdown("## 📄 Generate Optimized CV")
    st.markdown("Want me to automatically rewrite your resume using the STAR method and incorporate the missing skills?")
    
    if st.button("✨ Write My New CV", type="primary", use_container_width=True):
        if not jd_text:
            st.warning("JD text is missing!")
        else:
            with st.spinner("🤖 Writing your new CV... (this takes a minute)"):
                try:
                    cv_md = asyncio.run(generate_cv(jd_text, st.session_state.resume_text, res))
                    st.session_state.cv_markdown = cv_md
                    
                    # Convert to PDF
                    st.session_state.pdf_bytes = markdown_to_pdf(cv_md)
                    st.success("CV Generated Successfully!")
                except Exception as e:
                    st.error(f"Generation failed: {e}")

# Display Generated CV
if st.session_state.cv_markdown:
    st.markdown("---")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("### Preview")
        st.markdown(st.session_state.cv_markdown)
        
    with col2:
        st.markdown("### Actions")
        if st.session_state.pdf_bytes:
            st.download_button(
                label="📥 Download as PDF",
                data=st.session_state.pdf_bytes,
                file_name="Optimized_Resume.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary"
            )
        
        st.download_button(
            label="📝 Download Markdown (.md)",
            data=st.session_state.cv_markdown,
            file_name="optimized_resume.md",
            mime="text/markdown",
            use_container_width=True
        )
        
        with st.expander("Show Raw Markdown"):
            st.code(st.session_state.cv_markdown, language="markdown")
