# AI Chatbot for Supabase Inventory

This project is a web-based chatbot that allows users to ask natural language questions about an inventory database. The chatbot uses the OpenAI API to understand user questions, convert them into SQL queries, and generate friendly responses. The data is stored in a Supabase PostgreSQL database.

## Features

- **Natural Language Queries:** Ask questions like "how many stencils are horizontal?" instead of writing complex SQL.
- **Excel to Database:** Includes scripts to convert an Excel inventory file to CSV and upload it to Supabase.
- **Web Interface:** A simple and clean chat interface to interact with the chatbot.
- **Powered by OpenAI:** Uses state-of-the-art language models to understand and respond to users.

## Getting Started

Follow these steps to set up and run the project locally.

### 1. Prerequisites

- Python 3.8+
- A Supabase account (free tier is sufficient)
- An OpenAI API key

### 2. Clone the Repository

```bash
git clone <repository_url>
cd <repository_directory>
```

### 3. Install Dependencies

Install all the required Python packages using pip:

```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

You need to provide your API keys and Supabase project details.

1.  Create a file named `.env` in the root of the project.
2.  Copy the contents of `.env.example` into your new `.env` file.
3.  Fill in the values for your OpenAI API key and your Supabase project URL and anon key. You can find your Supabase details in your project's "Settings" > "API" page.

```
# .env file
OPENAI_API_KEY="your_openai_api_key_here"
SUPABASE_URL="your_supabase_url_here"
SUPABASE_KEY="your_supabase_anon_key_here"
```

### 5. Prepare the Initial Data

If you haven't already, convert the Excel inventory file to CSV format by running:
```bash
python excel_to_csv.py
```
This will create an `inventory.csv` file.

### 6. Set Up the Supabase Database

You need to create the database table and a special function to allow the chatbot to query the data.

1.  **Create the Table:**
    - Go to your Supabase project dashboard.
    - Navigate to the **SQL Editor**.
    - Click **New query**.
    - Open the `schema.sql` file in this project, copy its contents, paste them into the SQL Editor, and click **Run**. This will create the `inventory` table.

2.  **Create the SQL Function:**
    - In the same SQL Editor, click **New query** again.
    - Open the `function.sql` file, copy its contents, paste them into the editor, and click **Run**. This creates the `execute_sql` function that the backend will use.

### 7. Upload Data to Supabase

With the database set up, run the following script to upload the data from `inventory.csv` into your Supabase table:

```bash
python setup_supabase.py
```

### 8. Run the Application

You are now ready to start the chatbot's backend server:

```bash
python app.py
```

If everything is configured correctly, you will see a message that the application is running on `http://0.0.0.0:5000/`.

### 9. Use the Chatbot

Open your web browser and navigate to `http://127.0.0.1:5000`. You should see the chat interface, ready to answer your questions!
