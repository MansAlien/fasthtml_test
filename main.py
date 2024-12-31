from fasthtml.common import *
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from starlette.responses import StreamingResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import os.path
import pickle
import logging
import textwrap


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app, rt = fast_app()

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']

def get_google_drive_service():
    """Gets or creates Google Drive service."""
    try:
        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=8090)
            with open('token.pickle', 'wb') as token:
                pickle.dump(creds, token)
        
        service = build('drive', 'v3', credentials=creds)
        logger.info("Successfully created Drive service")
        return service
    except Exception as e:
        logger.error(f"Error creating Drive service: {str(e)}")
        raise

def get_or_create_folder(service, folder_name):
    """Get or create a folder in Google Drive."""
    try:
        # Search for the folder
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        folders = results.get('files', [])
        
        if folders:
            # Folder exists, return its ID
            logger.info(f"Found existing folder: {folder_name}")
            return folders[0]['id']
        else:
            # Create the folder
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            logger.info(f"Created new folder: {folder_name}")
            return folder['id']
    except Exception as e:
        logger.error(f"Error with folder operations: {str(e)}")
        raise

def upload_to_drive(buffer, filename):
    """Uploads a file to Google Drive."""
    try:
        service = get_google_drive_service()
        
        # Get or create the folder
        folder_id = get_or_create_folder(service, 'fasthtml_certificates')
        logger.info(f"Using folder ID: {folder_id}")
        
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        media = MediaIoBaseUpload(buffer, 
                                mimetype='image/png',
                                resumable=True)
        
        file = service.files().create(body=file_metadata,
                                    media_body=media,
                                    fields='id, name, webViewLink').execute()
        
        logger.info(f"File uploaded successfully. ID: {file.get('id')}")
        logger.info(f"File URL: {file.get('webViewLink')}")
        return file
    except Exception as e:
        logger.error(f"Error in upload_to_drive: {str(e)}")
        raise

@rt("/")
def get():
    form = Form(
        Input(id="name", name="name", placeholder="Your Name"),
        Input(id="job", name="job", placeholder="Your job"),
        Input(id="course", name="course", placeholder="Course Title"),
        Input(id="date", name="date", placeholder="Completion Date"),
        Button("Generate Certificate"),
        action="/generate", method="post"
    )
    return Titled("Certificate Generator", form)

@dataclass
class CertificateData:
    name: str
    course: str
    job: str
    date: str

@rt("/generate")
def post(cert: CertificateData):
    if not cert.name or not cert.course or not cert.date:
        return RedirectResponse("/", status_code=303)

    # Load the template image
    template_path = "temp.png"
    img = Image.open(template_path)

    # Prepare to draw on the image
    draw = ImageDraw.Draw(img)
    font_large = ImageFont.truetype("Rubik-Bold.ttf", 60)
    font_small = ImageFont.truetype("Rubik-Bold.ttf", 40)
    font_x_small = ImageFont.truetype("Rubik-Regular.ttf", 40)

    # Function to center the text
    def draw_centered_text(text, y_position, font_size=font_small, max_width=1200):
        # Wrap the text to fit the maximum width
        # Get the width of a space character to estimate how many characters fit in the max width
        space_width = font_size.getbbox(" ")[2]  # Get the width of a single space
        
        # Calculate the approximate number of characters that fit within max_width
        wrapped_text = textwrap.fill(text, width=int(max_width // space_width))  
        lines = wrapped_text.split("\n")
        
        # Draw each line of text
        y_offset = y_position
        for line in lines:
            # Calculate text size using getbbox
            bbox = draw.textbbox((0, 0), line, font=font_size)
            text_width = bbox[2] - bbox[0]
            x_position = (img.width - text_width) // 2
            draw.text((x_position, y_offset), line, font=font_size, fill="black")
            y_offset += font_size.getbbox(line)[3]  # Move to the next line height

    # Add centered text to the image
    draw_centered_text(f"بأن / {cert.name}", 580, font_size=font_large)
    draw_centered_text(cert.job, 640, font_size=font_large)
    draw_centered_text(f"Course: {cert.course}", 740, font_size=font_large, max_width=800)
    draw_centered_text(f"تحريراً {cert.date}", 950, font_size=font_x_small)

    # Save the image to an in-memory buffer
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    # Upload to Google Drive
    filename = f"certificate_{cert.name}_{cert.course}.png"
    try:
        file = upload_to_drive(buffer, filename)
        logger.info("Certificate generated and uploaded successfully")
        logger.info(f"File can be viewed at: {file.get('webViewLink')}")
    except Exception as e:
        logger.error(f"Failed to upload certificate: {str(e)}")

    # Reset buffer position for streaming response
    buffer.seek(0)

    return StreamingResponse(buffer, media_type="image/png", headers={
        "Content-Disposition": "attachment; filename=certificate.png"
    })

serve()
