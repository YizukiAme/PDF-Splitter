# PDF Splitter
A modern, cross-platform GUI tool to split PDF files with support for smart ranges, cut points, and custom naming templates. Built with Python and PySide6.
I developed this shit after realizing that almost every piece of software out there actually charges money for something as dumb as splitting a PDF.
<img width="2560" height="1519" alt="image" src="https://github.com/user-attachments/assets/7065a380-911a-4b6d-a28b-6642266c02be" />

## Features
-   **Multiple Splitting Modes**:
    -   **Smart Mode**: Intelligently parse inputs (e.g., `2 4` to extract pages between 2 and 4).
    -   **Ranges Mode**: Specify complex ranges (e.g., `1-3, 5, 8-10`).
    -   **Cut Points Mode**: Define points to cut the PDF into multiple documents.
-   **Theme Support**: Switch between light and dark modes.
-   **Customizable Output**: Define your own output directory and file naming patterns.
-   **Drag & Drop**: Easily add PDF files by dragging them into the application window.

## How to Use

The easiest way to use this application is to download the pre-compiled executable.
1.  Go to the [**Releases**](https://github.com/YizukiAme/PDF-Splitter/releases) page.
2.  Under the latest release, find the "Assets" section.
3.  Download the `.exe` file.
4.  Run the file. No installation is needed.

## For Developers (Running from Source)

1.  Clone the repository:
    ```bash
    git clone https://github.com/YizukiAme/PDF-Splitter.git
    cd PDF-Splitter
    ```
2.  Create and activate a virtual environment:
    ```bash
    python -m venv .venv
    # On Windows
    .venv\Scripts\activate
    ```
3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4.  Run the application:
    ```bash
    python "PDF Splitter.py"
    ```
