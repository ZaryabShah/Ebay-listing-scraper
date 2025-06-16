# eBay Listing Scraper Dashboard

A professional Streamlit web interface for managing and monitoring your eBay listing scraper.

## Features

🎯 **Keyword Management**
- Add/remove search keywords dynamically
- Real-time keyword monitoring
- Professional keyword display

📊 **Live Dashboard**
- Real-time scraper status monitoring
- Activity charts and statistics
- Recent activity tracking

⚙️ **Scraper Control**
- Start/stop scraper from the web interface
- Auto-refresh capabilities
- System status indicators

📋 **Logging & Monitoring**
- Real-time log viewing
- System health monitoring
- Professional status reporting

## Installation

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Telegram Settings**
   Edit the `Scraper.py` file to set your Telegram bot token and chat ID:
   ```python
   TG_BOT_TOKEN = "your_bot_token_here"
   TG_CHAT_ID = "your_chat_id_here"
   ```

## Usage

1. **Start the Streamlit Dashboard**
   ```bash
   streamlit run streamlit_ui.py --server.port 8501
   ```

2. **Access the Dashboard**
   Open your web browser and navigate to:
   ```
   http://localhost:8501
   ```

3. **Manage Keywords**
   - Use the "Keywords" tab to add/remove search terms
   - Keywords are automatically saved to the scraper configuration

4. **Control the Scraper**
   - Use the sidebar controls to start/stop the scraper
   - Monitor real-time status and activity

## Dashboard Sections

### 📝 Keywords Tab
- View all configured keywords
- Add new keywords with the form
- Remove keywords with the delete button
- Changes are saved automatically

### 📊 Dashboard Tab
- Overview metrics (status, keywords, activity)
- Activity charts showing scan frequency
- Recent activity table with timestamps

### ⚙️ Settings Tab
- View current configuration
- Telegram settings overview
- Future: Advanced configuration options

### 📋 Logs Tab
- Real-time system logs
- Status messages and updates
- Error reporting and diagnostics

## Professional Features

✨ **Modern UI Design**
- Clean, responsive interface
- Professional color scheme
- Intuitive navigation

🔄 **Real-time Updates**
- Auto-refresh functionality
- Live status monitoring
- Dynamic content updates

📱 **Mobile Friendly**
- Responsive design
- Works on all devices
- Touch-friendly controls

🛡️ **Robust Error Handling**
- Graceful error messages
- System stability
- User-friendly feedback

## Configuration

The dashboard automatically reads and writes to:
- `Scraper.py` - Main scraper configuration
- `state.json` - Scraper state and timestamps
- `requirements.txt` - Python dependencies

## Troubleshooting

**Port Already in Use**
```bash
streamlit run streamlit_ui.py --server.port 8502
```

**Permission Issues**
Make sure you have write permissions to the scraper directory.

**Scraper Won't Start**
Check that all dependencies are installed and Telegram credentials are configured.

## Support

For issues or questions:
1. Check the logs in the dashboard
2. Verify all dependencies are installed
3. Ensure Telegram configuration is correct

---

**Built with ❤️ using Streamlit**
