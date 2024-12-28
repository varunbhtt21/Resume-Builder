import os
import streamlit as st
import google.generativeai as genai
from dotenv import load_dotenv

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from tenacity import retry, wait_exponential, stop_after_attempt

import re
import logging

# -------------------------------------------------------------------
# Setup Logging
# -------------------------------------------------------------------
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

# -------------------------------------------------------------------
# Load environment variables from .env
# -------------------------------------------------------------------
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

# Configure the Gemini model
try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    logging.info("Gemini model configured successfully.")
except Exception as e:
    st.error(f"Failed to configure Gemini model: {e}")
    logging.error(f"Failed to configure Gemini model: {e}")
    st.stop()

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def ask_gemini(prompt: str) -> str:
    """
    Utility function to call the Gemini model and return the text response.
    Retries up to 3 times with exponential backoff in case of failures.
    """
    response = model.generate_content(prompt)
    return response.text

def send_email_plain_text(
    sender_email: str,
    sender_password: str,
    receiver_email: str,
    subject: str,
    body: str
):
    """
    Sends an email (through Gmail SMTP) with the resume in the email body.
    """
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject

    # Attach the resume text as the email body
    msg.attach(MIMEText(body, 'plain'))

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
    """
    Validates the format of an email address.
    """
    regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(regex, email) is not None

# -----------------------------------------------------------------------------
# Streamlit UI
# -----------------------------------------------------------------------------
st.title("AI-Powered Resume Builder")

# Hidden prompt that the user does NOT see
hidden_prompt = (
    "You are an expert career counselor and professional resume writer. "
    "Create a professional, high-quality resume tailored to the following Job Description. "
    "Ensure the resume follows a standard format and includes all relevant sections: "
    "1. Contact Information, "
    "2. Objective Statement, "
    "3. Skills, "
    "4. Projects, "
    "5. Education, "
    "6. Work Experience, "
    "7. Achievements. "
    "Highlight the skills and experiences that are most relevant to the Job Description. "
    "Use clear, concise, and impactful language to describe each section, ensuring that the resume effectively showcases the candidate's qualifications and suitability for the position. "
    "Make the resume ATS-friendly by using appropriate keywords from the Job Description."
)


# Use Streamlit's form to manage inputs and submissions
with st.form(key='resume_form'):
    # (1) Prompt for additional instructions (user sees only this text)
    prompt_input = st.text_area(
        "Add or modify the resume structure/instructions (optional):",
        value=(
            "Include any specific style guidelines, bullet points, or extra sections "
            "you want in your resume."
        ),
        height=150
    )
    
    # (2) JD input from the user (no file read)
    job_description = st.text_area(
        "Enter the Job Description (JD):",
        value="Paste or type the job description here...",
        height=200
    )
    
    # Submit button
    submit_button = st.form_submit_button(label='Generate Resume')

if submit_button:
    if not job_description.strip():
        st.warning("Please enter the Job Description (JD) before generating the resume.")
    else:
        # Combine hidden prompt + user's additional instructions + JD
        final_prompt = f"{hidden_prompt}\n\n{prompt_input}\n\nJob Description:\n{job_description}\n\nGenerate the resume based on the above."

        with st.spinner("Generating your resume..."):
            try:
                resume_text = ask_gemini(final_prompt)
                logging.info("Resume generated successfully.")
            except Exception as e:
                st.error(f"Error generating resume: {e}")
                logging.error(f"Error generating resume: {e}")
                resume_text = ""

        if resume_text:
            st.subheader("Your Generated Resume")
            # Display the resume with better formatting
            st.markdown(f"```\n{resume_text}\n```")

            # Expandable Email Section
            with st.expander("Send via Email"):
                receiver_email = st.text_input("Receiver Email Address")
                send_email_button = st.button("Send Email")
                
                if send_email_button:
                    if not receiver_email.strip():
                        st.warning("Please provide a receiver email.")
                    elif not is_valid_email(receiver_email):
                        st.warning("Please enter a valid email address.")
                    else:
                        success, message = send_email_plain_text(
                            sender_email=sender_email,
                            sender_password=sender_password,
                            receiver_email=receiver_email,
                            subject="Your AI-Generated Resume",
                            body=resume_text
                        )
                        if success:
                            st.success(message)
                        else:
                            st.error(f"Failed to send email: {message}")
