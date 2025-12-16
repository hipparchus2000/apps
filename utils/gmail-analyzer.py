import os
import pickle
import re
from collections import Counter
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# --- Configuration ---
# This file will store your OAuth tokens after the first successful authentication.
TOKEN_FILE = 'token.pickle'
# This file must be downloaded from the Google Cloud Console. See SETUP_INSTRUCTIONS.md.
CLIENT_SECRETS_FILE = 'client_secrets.json' 
# The scope needed to read email headers.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
MAX_RESULTS_PER_PAGE = 500

# --- Authentication and Setup ---

def get_gmail_service():
    """
    Handles the Google OAuth 2.0 flow. It checks for cached tokens in TOKEN_FILE.
    If tokens are expired or missing, it triggers the browser-based authorization flow,
    saves new tokens, and returns the authenticated Gmail API service object.
    """
    creds = None
    # 1. Check for existing credentials
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    # 2. Handle expired or missing credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh expired token automatically
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                raise FileNotFoundError(
                    f"Required file '{CLIENT_SECRETS_FILE}' not found. "
                    "Please download it from your Google Cloud Console and place it "
                    "in the same directory as this script."
                )

            # Initiate the local webserver flow for user authentication
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            # This opens a browser window for the user to grant permission
            creds = flow.run_local_server(port=0)

        # 3. Save the updated/new credentials
        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    # 4. Build and return the API service
    return build('gmail', 'v1', credentials=creds)

# --- Data Extraction and Analysis ---

def extract_email(from_string):
    """
    Extracts the clean email address from the "From" header string.
    Handles common formats like "User Name <email@domain.com>".
    """
    # Use regex to find email within angle brackets
    match = re.search(r'<(.+?)>', from_string)
    if match:
        return match.group(1).lower()
    
    # Fallback: look for parts containing '@'
    parts = from_string.split()
    for part in parts:
        if '@' in part:
            return part.lower().strip('<>(),')
            
    # Default return the cleaned full string
    return from_string.lower().strip()

def get_senders_count(service):
    """
    Fetches message IDs page by page, then fetches the 'From' header for each message
    to count sender frequencies and domain frequencies.
    """
    sender_counts = Counter()
    domain_counts = Counter()
    total_emails = 0
    page_token = None
    page_count = 0

    print("Starting full inbox analysis. This may take a while for large inboxes.")

    # Loop to fetch messages, handling pagination (nextPageToken)
    while True:
        page_count += 1
        print(f"\n--- Fetching page {page_count} of message IDs... ---")

        try:
            # 1. List messages (efficiently grabs IDs)
            results = service.users().messages().list(
                userId='me',
                maxResults=MAX_RESULTS_PER_PAGE,
                pageToken=page_token
            ).execute()
        except Exception as e:
            print(f"An error occurred during message listing (page {page_count}): {e}")
            break

        messages = results.get('messages', [])

        if not messages:
            print("Finished fetching message IDs.")
            break

        total_emails += len(messages)
        print(f"Found {len(messages)} messages on this page. Total IDs collected: {total_emails}")

        # 2. Fetch 'From' header for each message ID
        for i, message in enumerate(messages):
            # Print progress every 100 messages
            if (i + 1) % 100 == 0 or (i + 1) == len(messages):
                 print(f"   -> Processing message {i+1} of {len(messages)} on page {page_count}...")

            try:
                # Get the message metadata, specifically requesting the 'From' header
                msg = service.users().messages().get(
                    userId='me',
                    id=message['id'],
                    format='metadata',
                    metadataHeaders=['From']
                ).execute()

                headers = msg.get('payload', {}).get('headers', [])

                # Find the 'From' header
                from_header = next((h for h in headers if h['name'].lower() == 'from'), None)

                if from_header:
                    email = extract_email(from_header['value'])
                    sender_counts[email] += 1

                    # Extract domain from email address
                    if '@' in email:
                        domain = email.split('@')[1]
                        domain_counts[domain] += 1

            except Exception as e:
                # Log error and skip to the next message
                print(f"   -> Could not fetch message ID {message['id']}: {e}. Skipping.")
                continue

        # Get token for the next page, if available
        page_token = results.get('nextPageToken')

        if not page_token:
            break

    return sender_counts, domain_counts, total_emails

# --- Main Execution and Display ---

def main():
    try:
        service = get_gmail_service()
        sender_counts, domain_counts, total_emails = get_senders_count(service)

        # Sort the results by count in descending order
        sorted_domains = sorted(domain_counts.items(), key=lambda item: item[1], reverse=True)
        sorted_senders = sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)

        print("\n" + "="*70)
        print("                     GMAIL SENDER ANALYSIS RESULTS")
        print("="*70)
        print(f"Total Emails Analyzed: {total_emails}")
        print(f"Unique Senders:        {len(sorted_senders)}")
        print(f"Unique Domains:        {len(sorted_domains)}")
        print("="*70)

        # Display top 50 domains
        print("Top 50 Domains (Rank | Count | Domain):")
        print("-"*70)

        if not sorted_domains:
            print("No domains found in your inbox.")
        else:
            for rank, (domain, count) in enumerate(sorted_domains[:50], 1):
                # Format output for alignment
                print(f"{rank:4}. | {count:6} | {domain}")

            if len(sorted_domains) > 50:
                print(f"\n... and {len(sorted_domains) - 50} more unique domains not shown.")

        print("\n" + "="*70)
        print("Top Senders (Rank | Count | Email Address):")

        if not sorted_senders:
            print("No senders found in your inbox.")
            return

        # Display top 200 senders
        for rank, (email, count) in enumerate(sorted_senders[:200], 1):
            # Format output for alignment
            print(f"{rank:4}. | {count:6} | {email}")

        if len(sorted_senders) > 200:
             print(f"\n... and {len(sorted_senders) - 200} more unique senders not shown.")


    except FileNotFoundError as e:
        print("\n" + "="*70)
        print(f"SETUP ERROR: {e}")
        print("The script requires the 'client_secrets.json' file to run. Please check the setup guide.")
        print("="*70)
    except Exception as e:
        print("\n" + "="*70)
        print(f"A critical error occurred: {e}")
        print("Ensure you have granted the 'Gmail Readonly' permission during authentication.")
        print("="*70)


if __name__ == '__main__':
    main()