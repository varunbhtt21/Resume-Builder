import os
import streamlit as st
import google.generativeai as genai
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from tenacity import retry, wait_exponential, stop_after_attempt
import re
import logging
from fpdf import FPDF
import io

# Setup logging
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

# Load environment variables
load_dotenv()

api_key = os.getenv("GENAI_API_KEY")
sender_email = os.getenv("SENDER_EMAIL")
sender_password = os.getenv("SENDER_PASSWORD")

# Validate environment variables
missing_vars = []
if not api_key:
    missing_vars.append("GENAI_API_KEY")
if not sender_email:
    missing_vars.append("SENDER_EMAIL")
if not sender_password:
    missing_vars.append("SENDER_PASSWORD")

if missing_vars:
    st.error(f"Missing environment variables: {', '.join(missing_vars)}. Please check your .env file.")
    logging.error(f"Missing environment variables: {', '.join(missing_vars)}.")
    st.stop()

# Configure Gemini model
try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    logging.info("Gemini model configured successfully.")
except Exception as e:
    st.error(f"Failed to configure Gemini model: {e}")
    logging.error(f"Failed to configure Gemini model: {e}")
    st.stop()

class ResumePDF(FPDF):
    def __init__(self):
        super().__init__()
        self.left_column_width = 65  # mm
        self.right_column_width = 125  # mm
        self.margin = 10  # mm
        self.set_margins(self.margin, self.margin, self.margin)
        self.current_y_left = 0
        self.current_y_right = 0
    
    def add_name_section(self, name, email, phone):
        """Add the name and contact section at the top"""
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, name, ln=True)
        self.set_font('Arial', '', 10)
        self.cell(0, 5, f"{email} | {phone}", ln=True)
        self.ln(5)
        self.current_y_left = self.get_y()
        self.current_y_right = self.get_y()

    def add_section_title(self, title, column='left'):
        """Add a section title with consistent formatting"""
        original_y = self.get_y()
        if column == 'left':
            self.set_xy(self.margin, self.current_y_left)
        else:
            self.set_xy(self.margin + self.left_column_width + 10, self.current_y_right)
        
        self.set_font('Arial', 'B', 11)
        self.cell(0, 6, title.upper(), ln=True)
        self.ln(2)
        
        if column == 'left':
            self.current_y_left = self.get_y()
        else:
            self.current_y_right = self.get_y()

    def add_content_left(self, content, is_bullet=False):
        """Add content to the left column"""
        self.set_xy(self.margin, self.current_y_left)
        self.set_font('Arial', '', 9)
        if is_bullet:
            content = '• ' + content
        self.multi_cell(self.left_column_width, 5, content)
        self.current_y_left = self.get_y()

    def add_content_right(self, content, is_bullet=False):
        """Add content to the right column"""
        self.set_xy(self.margin + self.left_column_width + 10, self.current_y_right)
        self.set_font('Arial', '', 9)
        if is_bullet:
            content = '• ' + content
        self.multi_cell(self.right_column_width, 5, content)
        self.current_y_right = self.get_y()

def sanitize_text(text: str) -> str:
    """Sanitize text to handle special characters"""
    replacements = {
        '\u2013': '-',  # en dash
        '\u2014': '-',  # em dash
        '\u2018': "'",  # left single quotation
        '\u2019': "'",  # right single quotation
        '\u201C': '"',  # left double quotation
        '\u201D': '"',  # right double quotation
        '\u2022': '*',  # bullet point
        '\u2026': '...',  # horizontal ellipsis
        '\u2028': '\n',  # line separator
        '\u2029': '\n\n',  # paragraph separator
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    return text.encode('ascii', errors='replace').decode()

def parse_resume_sections(resume_text):
    """Parse the resume text into structured sections"""
    sections = {}
    current_section = None
    current_content = []
    
    for line in resume_text.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        if line.isupper() or line.endswith(':'):
            if current_section:
                sections[current_section] = current_content
            current_section = line.rstrip(':')
            current_content = []
        else:
            current_content.append(line)
    
    if current_section:
        sections[current_section] = current_content
    
    return sections

def create_pdf(resume_text: str) -> bytes:
    """Creates a PDF document from the resume text with two-column layout"""
    resume_text = sanitize_text(resume_text)
    sections = parse_resume_sections(resume_text)
    
    pdf = ResumePDF()
    pdf.add_page()
    
    # Add name and contact info
    contact_info = sections.get('CONTACT INFORMATION', ['Name', 'email@example.com | Phone'])
    name = contact_info[0]
    contact = contact_info[1] if len(contact_info) > 1 else ''
    email, phone = contact.split('|') if '|' in contact else (contact, '')
    pdf.add_name_section(name, email.strip(), phone.strip())
    
    # Define section order
    left_sections = ['EDUCATION', 'SKILLS', 'TECHNICAL SKILLS', 'COURSEWORK', 'ACHIEVEMENTS', 'LINKS']
    right_sections = ['EXPERIENCE', 'WORK EXPERIENCE', 'PROJECTS', 'PROFESSIONAL EXPERIENCE']
    
    # Process left column
    for section in left_sections:
        if section in sections:
            pdf.add_section_title(section, 'left')
            for content in sections[section]:
                if content.strip().startswith('•'):
                    pdf.add_content_left(content.strip()[1:].strip(), True)
                else:
                    pdf.add_content_left(content)
            pdf.current_y_left += 5
    
    # Reset right column Y position
    pdf.current_y_right = pdf.margin + 25
    
    # Process right column
    for section in right_sections:
        if section in sections:
            pdf.add_section_title(section, 'right')
            for content in sections[section]:
                if content.strip().startswith('•'):
                    pdf.add_content_right(content.strip()[1:].strip(), True)
                else:
                    pdf.add_content_right(content)
            pdf.current_y_right += 5
    
    return pdf.output(dest='S').encode('latin-1')

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def ask_gemini(prompt: str) -> str:
    """Call the Gemini model with retry logic"""
    response = model.generate_content(prompt)
    return response.text

def send_email_with_attachment(
    sender_email: str,
    sender_password: str,
    receiver_email: str,
    subject: str,
    body: str,
    pdf_data: bytes
):
    """Send email with resume as text and PDF attachment"""
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, 'plain'))
    
    pdf_attachment = MIMEApplication(pdf_data, _subtype='pdf')
    pdf_attachment.add_header('Content-Disposition', 'attachment', filename='resume.pdf')
    msg.attach(pdf_attachment)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, receiver_email, msg.as_string())
        server.quit()
        logging.info(f"Email sent successfully to {receiver_email}.")
        return True, "Email sent successfully!"
    except Exception as e:
        logging.error(f"Failed to send email to {receiver_email}: {e}")
        return False, str(e)

def is_valid_email(email: str) -> bool:
    """Validate email format"""
    regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(regex, email) is not None

# Streamlit UI
st.title("AI-Powered Resume Builder")

# Hidden prompt
hidden_prompt = """
You are an expert resume writer. Create a professional, ATS-friendly resume following this exact format:

CONTACT INFORMATION
[Full Name]
[Email] | [Phone]

The resume should have two columns:

Left column sections (in order):
- EDUCATION (with university name, degree, year, location, GPA)
- SKILLS (technical skills, programming languages)
- COURSEWORK (relevant courses)
- ACHIEVEMENTS (bullet points)
- LINKS (Github, LinkedIn)

Right column sections (in order):
- EXPERIENCE (with company name, position, dates)
  • Use bullet points for responsibilities and achievements
  • Focus on quantifiable achievements and technical details
  • Use action verbs and specific technologies
- PROJECTS (with detailed technical descriptions)
  • Include technologies used
  • Highlight technical challenges solved
  • Mention scale and impact

Use consistent formatting:
- ALL CAPS for section headers
- Bullet points for lists
- Clear hierarchy of information
- Concise, technical language
- Focus on relevant skills and technologies for the job description
"""

# Form for user input
with st.form(key='resume_form'):
    contact_info = st.text_area(
        "Enter your contact information:",
        value="Full Name\nemail@example.com | +1234567890",
        height=100
    )
    
    prompt_input = st.text_area(
        "Add or modify the resume structure/instructions (optional):",
        value="Include any specific style guidelines or extra sections you want in your resume.",
        height=150
    )
    
    job_description = st.text_area(
        "Enter the Job Description (JD):",
        value="Paste or type the job description here...",
        height=200
    )
    
    submit_button = st.form_submit_button(label='Generate Resume')

if submit_button:
    if not job_description.strip():
        st.warning("Please enter the Job Description (JD) before generating the resume.")
    else:
        final_prompt = f"{hidden_prompt}\n\nContact Information:\n{contact_info}\n\nAdditional Instructions:\n{prompt_input}\n\nJob Description:\n{job_description}\n\nGenerate the resume based on the above."

        with st.spinner("Generating your resume..."):
            try:
                resume_text = ask_gemini(final_prompt)
                pdf_data = create_pdf(resume_text)
                logging.info("Resume generated successfully.")
            except Exception as e:
                st.error(f"Error generating resume: {e}")
                logging.error(f"Error generating resume: {e}")
                resume_text = ""
                pdf_data = None

        if resume_text:
            st.subheader("Your Generated Resume")
            st.markdown(f"```\n{resume_text}\n```")

            st.download_button(
                label="Download Resume as PDF",
                data=pdf_data,
                file_name="resume.pdf",
                mime="application/pdf"
            )

            with st.expander("Send via Email"):
                receiver_email = st.text_input("Receiver Email Address")
                send_email_button = st.button("Send Email")
                
                if send_email_button:
                    if not receiver_email.strip():
                        st.warning("Please provide a receiver email.")
                    elif not is_valid_email(receiver_email):
                        st.warning("Please enter a valid email address.")
                    else:
                        success, message = send_email_with_attachment(
                            sender_email=sender_email,
                            sender_password=sender_password,
                            receiver_email=receiver_email,
                            subject="Your AI-Generated Resume",
                            body=resume_text,
                            pdf_data=pdf_data
                        )
                        if success:
                            st.success(message)
                        else:
                            st.error(f"Failed to send email: {message}")