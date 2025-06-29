"""
Professional Streamlit UI for eBay Listing Scraper
==================================================
A modern, responsive web interface for managing eBay search keywords and monitoring scraper status.
"""

import streamlit as st
import json
import time
import threading
import subprocess
import os
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List, Optional
import requests

# Configuration
STATE_PATH = Path("state.json")
SCRAPER_SCRIPT = "Scraper.py"
PID_FILE = Path("scraper.pid")
LOG_FILE = Path("scraper.log")

# Setup logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="eBay Listing Scraper Dashboard",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1e3a8a;
        text-align: center;
        margin-bottom: 2rem;
        font-weight: 700;
    }
    
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
    }
    
    .status-running {
        color: #10b981;
        font-weight: bold;
    }
    
    .status-stopped {
        color: #ef4444;
        font-weight: bold;
    }
    
    .keyword-item {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    
    .success-message {
        background-color: #dcfce7;
        border: 1px solid #bbf7d0;
        color: #166534;
        padding: 0.75rem;
        border-radius: 6px;
        margin: 1rem 0;
    }
    
    .warning-message {
        background-color: #fef3c7;
        border: 1px solid #fde68a;
        color: #92400e;
        padding: 0.75rem;
        border-radius: 6px;
        margin: 1rem 0;
    }
    
    .sidebar-section {
        background-color: #f1f5f9;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

class ScraperManager:
    def __init__(self):
        self.process = None
        self.is_running = False
        self.pid = None
        
    def is_process_running(self, pid):
        """Check if a process is running by PID"""
        try:
            if os.name == 'nt':  # Windows
                import psutil
                return psutil.pid_exists(pid)
            else:  # Unix/Linux
                os.kill(pid, 0)
                return True
        except:
            return False
    
    def get_running_scraper_pid(self):
        """Get the PID of currently running scraper if any"""
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                if self.is_process_running(pid):
                    return pid
                else:
                    # Clean up stale PID file
                    PID_FILE.unlink()
                    return None
            except:
                return None
        return None
    
    def start_scraper(self):
        """Start the scraper process"""
        # Check if already running
        existing_pid = self.get_running_scraper_pid()
        if existing_pid:
            logger.info(f"Scraper already running with PID {existing_pid}")
            return False, f"Scraper is already running (PID: {existing_pid})"
        
        try:
            # Start the process
            log_file = open(LOG_FILE, "a", buffering=1)       # line-buffered

            self.process = subprocess.Popen(
                [sys.executable, "-u", SCRAPER_SCRIPT],       # <- -u = unbuffered
                stdout=log_file,
                stderr=log_file,
                text=True,
                bufsize=1,                                    # line buffering
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )

            
            self.pid = self.process.pid
            self.is_running = True
            
            # Save PID to file
            with open(PID_FILE, 'w') as f:
                f.write(str(self.pid))
            
            logger.info(f"Scraper started successfully with PID {self.pid}")
            return True, f"Scraper started successfully! (PID: {self.pid})"
        except Exception as e:
            logger.error(f"Failed to start scraper: {str(e)}")
            return False, f"Failed to start scraper: {str(e)}"
    
    def stop_scraper(self):
        """Stop the scraper process"""
        existing_pid = self.get_running_scraper_pid()
        
        if not existing_pid:
            return False, "No scraper process found!"
        
        try:
            if os.name == 'nt':  # Windows
                import psutil
                process = psutil.Process(existing_pid)
                process.terminate()
                process.wait(timeout=10)
            else:  # Unix/Linux
                os.kill(existing_pid, 15)  # SIGTERM
                time.sleep(2)
                if self.is_process_running(existing_pid):
                    os.kill(existing_pid, 9)  # SIGKILL
            
            # Clean up PID file
            if PID_FILE.exists():
                PID_FILE.unlink()
            
            # Clean up state.json file
            if STATE_PATH.exists():
                try:
                    STATE_PATH.unlink()
                    logger.info("🧹 Cleaned up state.json file")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to remove state.json file: {e}")
            
            self.is_running = False
            self.process = None
            self.pid = None
            
            logger.info(f"Scraper stopped successfully (PID: {existing_pid})")
            return True, f"Scraper stopped successfully! (PID: {existing_pid})"
        except Exception as e:
            logger.error(f"Failed to stop scraper: {str(e)}")
            return False, f"Failed to stop scraper: {str(e)}"
    
    def get_status(self):
        """Get current scraper status - works across sessions"""
        existing_pid = self.get_running_scraper_pid()
        if existing_pid:
            self.is_running = True
            self.pid = existing_pid
            return "Running"
        else:
            self.is_running = False
            self.pid = None
            return "Stopped"
    
    def get_process_info(self):
        """Get detailed process information"""
        existing_pid = self.get_running_scraper_pid()
        if existing_pid:
            try:
                if os.name == 'nt':  # Windows
                    import psutil
                    process = psutil.Process(existing_pid)
                    return {
                        'pid': existing_pid,
                        'status': process.status(),
                        'cpu_percent': process.cpu_percent(),
                        'memory_info': process.memory_info(),
                        'create_time': datetime.fromtimestamp(process.create_time())
                    }
                else:
                    return {'pid': existing_pid, 'status': 'running'}
            except:
                pass
        return None

def get_recent_logs(num_lines=50):
    """Read recent logs from the log file"""
    try:
        if not LOG_FILE.exists():
            return ["No logs available yet."]
        
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-num_lines:] if line.strip()]
    except Exception as e:
        return [f"Error reading logs: {str(e)}"]

def write_log(message, level="INFO"):
    """Write a log message to both file and console"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {level}: {message}"
    
    # Write to file
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')
    except:
        pass
    
    # Also log using Python logger
    if level == "ERROR":
        logger.error(message)
    elif level == "WARNING":
        logger.warning(message)
    else:
        logger.info(message)

def load_keywords():
    """Load keywords from the scraper file"""
    try:
        with open(SCRAPER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract keywords from the KEYWORDS list
        import re
        keywords_match = re.search(r'KEYWORDS:\s*List\[str\]\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if keywords_match:
            keywords_str = keywords_match.group(1)
            keywords = []
            for line in keywords_str.split(','):
                line = line.strip().strip('"\'').strip()
                if line and not line.startswith('#') and line != '':
                    keywords.append(line)
            return keywords
        
        # Return default keywords if parsing fails
        default_keywords = ["Playstation 5", "Grafikkarte", "Nintendo Switch"]
        return default_keywords
    except Exception as e:
        st.error(f"Error loading keywords: {str(e)}")
        return ["Playstation 5", "Grafikkarte", "Nintendo Switch"]  # Default keywords

def save_keywords(keywords):
    """Save keywords to the scraper file"""
    try:
        with open(SCRAPER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Format keywords for Python list
        keywords_formatted = ',\n    '.join([f'"{kw}"' for kw in keywords])
        keywords_list = f'KEYWORDS: List[str] = [\n    {keywords_formatted},\n]'
        
        # Replace the KEYWORDS list in the file
        import re
        new_content = re.sub(
            r'KEYWORDS:\s*List\[str\]\s*=\s*\[.*?\]',
            keywords_list,
            content,
            flags=re.DOTALL
        )
        
        with open(SCRAPER_SCRIPT, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True, "Keywords saved successfully!"
    except Exception as e:
        return False, f"Error saving keywords: {str(e)}"


def load_urls():
    """Load complete URLs from the scraper file"""
    try:
        with open(SCRAPER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract URLs from the COMPLETE_URLS list
        import re
        urls_match = re.search(r'COMPLETE_URLS:\s*List\[str\]\s*=\s*\[(.*?)\]', content, re.DOTALL)
        if urls_match:
            urls_str = urls_match.group(1)
            urls = []
            for line in urls_str.split(','):
                line = line.strip().strip('"\'').strip()
                if line and not line.startswith('#') and line != '' and line.startswith(('http://', 'https://')):
                    urls.append(line)
            return urls
        
        # Return empty list if parsing fails
        return []
    except Exception as e:
        st.error(f"Error loading URLs: {str(e)}")
        return []


def save_urls(urls):
    """Save complete URLs to the scraper file"""
    try:
        with open(SCRAPER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Format URLs for Python list
        if urls:
            urls_formatted = ',\n    '.join([f'"{url}"' for url in urls])
            urls_list = f'COMPLETE_URLS: List[str] = [\n    {urls_formatted},\n]'
        else:
            urls_list = 'COMPLETE_URLS: List[str] = [\n    # Example: "https://www.ebay.de/sch/i.html?_from=R40&_nkw=nintendo+switch&_sacat=139971&_sop=10&LH_BIN=1&rt=nc&LH_PrefLoc=3",\n    # Add your complete eBay search URLs here\n]'
        
        # Replace the COMPLETE_URLS list in the file
        new_content = re.sub(
            r'COMPLETE_URLS:\s*List\[str\]\s*=\s*\[.*?\]',
            urls_list,
            content,
            flags=re.DOTALL
        )
        
        with open(SCRAPER_SCRIPT, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return True, "URLs saved successfully!"
    except Exception as e:
        return False, f"Error saving URLs: {str(e)}"

def load_state():
    """Load scraper state"""
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def get_scraper_stats():
    """Get scraper statistics"""
    state = load_state()
    keywords = load_keywords()
    urls = load_urls()
    
    stats = {
        'total_keywords': len(keywords),
        'total_urls': len(urls),
        'total_inputs': len(keywords) + len(urls),
        'active_scans': len(state),
        'last_update': None,
        'total_scans': 0
    }
    
    if state:
        timestamps = []
        for ts in state.values():
            try:
                timestamps.append(datetime.fromisoformat(ts))
            except:
                pass
        stats['last_update'] = max(timestamps) if timestamps else None
        stats['total_scans'] = len(state)
    
    return stats

def create_activity_chart():
    """Create activity chart from state data"""
    state = load_state()
    if not state:
        return None
    
    data = []
    for keyword, timestamp in state.items():
        try:
            dt = datetime.fromisoformat(timestamp)
            data.append({
                'Keyword': keyword,
                'Last Scan': dt,
                'Hours Ago': (datetime.now() - dt).total_seconds() / 3600
            })
        except:
            pass
    
    df = pd.DataFrame(data)
    
    if len(df) > 0:
        fig = px.bar(
            df, 
            x='Keyword', 
            y='Hours Ago',
            title='Hours Since Last Scan per Keyword',
            color='Hours Ago',
            color_continuous_scale='Viridis'
        )
        fig.update_layout(
            xaxis_tickangle=45,
            height=400,
            showlegend=False
        )
        return fig
    return None

# Initialize session state
if 'scraper_manager' not in st.session_state:
    st.session_state.scraper_manager = ScraperManager()

# Main UI
def main():
    # Header
    st.markdown('<h1 class="main-header">🛒 eBay Listing Scraper Dashboard</h1>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.header("🎛️ Control Panel")
          # Scraper controls with detailed status
        scraper_status = st.session_state.scraper_manager.get_status()
        process_info = st.session_state.scraper_manager.get_process_info()
        
        if scraper_status == "Running":
            st.markdown('<p class="status-running">● Status: Running</p>', unsafe_allow_html=True)
              # Show process details if available
            if process_info:
                st.markdown(f"**PID:** {process_info['pid']}")
                if 'cpu_percent' in process_info:
                    st.markdown(f"**CPU:** {process_info['cpu_percent']:.1f}%")
                if 'create_time' in process_info:
                    runtime = datetime.now() - process_info['create_time']
                    st.markdown(f"**Runtime:** {str(runtime).split('.')[0]}")
            
            if st.button("🛑 Stop Scraper", type="secondary", use_container_width=True):
                success, message = st.session_state.scraper_manager.stop_scraper()
                if success:
                    st.success(message)
                else:
                    st.error(message)
                st.rerun()
        else:
            st.markdown('<p class="status-stopped">● Status: Stopped</p>', unsafe_allow_html=True)
            if st.button("▶️ Start Scraper", type="primary", use_container_width=True):
                success, message = st.session_state.scraper_manager.start_scraper()
                if success:
                    st.success(message)
                else:
                    st.error(message)
                st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Auto-refresh toggle
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.header("🔄 Auto Refresh")
        auto_refresh = st.checkbox("Enable auto-refresh (30s)", value=False)
        if auto_refresh:
            time.sleep(30)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Quick stats
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.header("📊 Quick Stats")
        stats = get_scraper_stats()
        st.metric("Total Keywords", stats['total_keywords'])
        st.metric("Active Scans", stats['active_scans'])
        if stats['last_update']:
            time_ago = datetime.now() - stats['last_update']
            hours_ago = int(time_ago.total_seconds() / 3600)
            st.metric("Last Activity", f"{hours_ago}h ago")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Main content area
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Search Inputs", "📊 Dashboard", "⚙️ Settings", "📋 Logs"])
    
    with tab1:
        st.header("🔍 Search Input Management")
        
        # Create sub-tabs for keywords and URLs
        sub_tab1, sub_tab2 = st.tabs(["🔤 Keywords", "🔗 Complete URLs"])
        
        with sub_tab1:
            st.subheader("Keyword Search Management")
            
            # Current keywords
            keywords = load_keywords()
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.subheader("Current Keywords")
                if keywords:
                    for i, keyword in enumerate(keywords):
                        col_kw, col_del = st.columns([4, 1])
                        with col_kw:
                            st.markdown(f"""
                                <div style="
                                    background-color: #f8fafc; 
                                    border: 1px solid #e2e8f0; 
                                    border-radius: 8px; 
                                    padding: 1rem; 
                                    margin: 0.5rem 0;
                                    display: flex;
                                    align-items: center;
                                    color: #1e293b;
                                ">
                                    🔍 <strong>{keyword}</strong>
                                </div>
                                """, unsafe_allow_html=True)
                        with col_del:
                            if st.button("🗑️", key=f"del_kw_{i}", help="Delete keyword", type="secondary"):
                                keywords.remove(keyword)
                                success, message = save_keywords(keywords)
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                else:
                    st.info("No keywords configured. Add some keywords to start monitoring.")
            
            with col2:
                st.subheader("➕ Add New Keyword")
                
                # Direct input method
                st.write("**Method 1: Quick Add**")
                new_keyword = st.text_input(
                    "Enter keyword:", 
                    placeholder="e.g., iPhone 15 Pro",
                    key="quick_keyword_input"
                )
                
                if st.button("➕ Add Keyword", type="primary", key="add_quick"):
                    if new_keyword and new_keyword.strip():
                        new_keyword = new_keyword.strip()
                        if new_keyword not in keywords:
                            keywords.append(new_keyword)
                            success, message = save_keywords(keywords)
                            if success:
                                st.success(f"✅ Added keyword: **{new_keyword}**")
                                st.rerun()
                            else:
                                st.error(message)
                        else:
                            st.warning("⚠️ Keyword already exists!")
                    else:
                        st.error("Please enter a keyword!")
            
            st.divider()
            
            # Form method for more structured input
            st.write("**Method 2: Form Input**")
            with st.form("add_keyword_form", clear_on_submit=True):
                form_keyword = st.text_input(
                    "Keyword:", 
                    placeholder="Enter search term...",
                    help="Enter the product or term you want to monitor on eBay"
                )
                
                col_submit, col_clear = st.columns(2)
                with col_submit:
                    submitted = st.form_submit_button("🚀 Add", type="primary", use_container_width=True)
                with col_clear:
                    if st.form_submit_button("🗑️ Clear", use_container_width=True):
                        st.rerun()
                
                if submitted and form_keyword and form_keyword.strip():
                    form_keyword = form_keyword.strip()
                    if form_keyword not in keywords:
                        keywords.append(form_keyword)
                        success, message = save_keywords(keywords)
                        if success:
                            st.success(f"✅ Added keyword: **{form_keyword}**")
                            st.rerun()
                        else:
                            st.error(message)
                    else:
                        st.warning("⚠️ Keyword already exists!")
                elif submitted:
                    st.error("Please enter a valid keyword!")
            
            # Bulk add section
            st.divider()
            st.write("**Method 3: Bulk Add**")
            bulk_keywords = st.text_area(
                "Multiple keywords (one per line):",
                placeholder="iPhone 15\nSamsung Galaxy\nPlayStation 5",
                height=100,
                help="Enter multiple keywords, one per line"
            )
            
            if st.button("📦 Add All", type="secondary", key="bulk_add"):
                if bulk_keywords.strip():
                    new_keywords = [kw.strip() for kw in bulk_keywords.strip().split('\n') if kw.strip()]
                    added_count = 0
                    for kw in new_keywords:
                        if kw not in keywords:
                            keywords.append(kw)
                            added_count += 1
                    
                    if added_count > 0:
                        success, message = save_keywords(keywords)
                        if success:
                            st.success(f"✅ Added {added_count} keywords!")
                            st.rerun()
                        else:
                            st.error(message)
                    else:
                        st.info("No new keywords to add (all already exist)")
                else:
                    st.error("Please enter keywords to add!")
        
        with sub_tab2:
            st.subheader("Complete URL Management")
            
            # Current URLs
            urls = load_urls()
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.subheader("Current URLs")
                if urls:
                    for i, url in enumerate(urls):
                        col_url, col_del = st.columns([4, 1])
                        with col_url:
                            # Truncate long URLs for display
                            display_url = url[:80] + "..." if len(url) > 80 else url
                            st.markdown(f"""
                                <div style="
                                    background-color: #eff6ff; 
                                    border: 1px solid #dbeafe; 
                                    border-radius: 8px; 
                                    padding: 1rem; 
                                    margin: 0.5rem 0;
                                    color: #1e40af;
                                ">
                                    🔗 <strong>{display_url}</strong>
                                    <br><small style="color: #64748b;">Full URL: {url}</small>
                                </div>
                                """, unsafe_allow_html=True)
                        with col_del:
                            if st.button("🗑️", key=f"del_url_{i}", help="Delete URL", type="secondary"):
                                urls.remove(url)
                                success, message = save_urls(urls)
                                if success:
                                    st.success(message)
                                    st.rerun()
                                else:
                                    st.error(message)
                else:
                    st.info("No complete URLs configured. Add eBay search URLs to monitor specific searches.")
            
            with col2:
                st.subheader("🔗 Add New URL")
                
                # Help text
                st.info("""
                **How to get eBay search URLs:**
                1. Go to eBay and perform your search
                2. Apply any filters (price, condition, etc.)
                3. Copy the complete URL from your browser
                4. Paste it here
                """)
                
                # Direct input method
                st.write("**Add Complete eBay URL**")
                new_url = st.text_area(
                    "Enter complete eBay search URL:", 
                    placeholder="https://www.ebay.de/sch/i.html?_from=R40&_nkw=...",
                    height=100,
                    key="url_input"
                )
                
                if st.button("🔗 Add URL", type="primary", key="add_url"):
                    if new_url and new_url.strip():
                        new_url = new_url.strip()
                        if new_url.startswith(('http://', 'https://')) and 'ebay' in new_url.lower():
                            if new_url not in urls:
                                urls.append(new_url)
                                success, message = save_urls(urls)
                                if success:
                                    st.success(f"✅ Added URL successfully!")
                                    st.rerun()
                                else:
                                    st.error(message)
                            else:
                                st.warning("⚠️ URL already exists!")
                        else:
                            st.error("❌ Please enter a valid eBay URL (must start with http:// or https:// and contain 'ebay')")
                    else:
                        st.error("Please enter a URL!")
                
                st.divider()
                
                # Bulk add section
                st.write("**Bulk Add URLs**")
                bulk_urls = st.text_area(
                    "Multiple URLs (one per line):",
                    placeholder="https://www.ebay.de/sch/...\nhttps://www.ebay.de/sch/...",
                    height=100,
                    help="Enter multiple eBay URLs, one per line"
                )
                
                if st.button("📦 Add All URLs", type="secondary", key="bulk_add_urls"):
                    if bulk_urls.strip():
                        new_urls = [url.strip() for url in bulk_urls.strip().split('\n') if url.strip()]
                        added_count = 0
                        invalid_count = 0
                        
                        for url in new_urls:
                            if url.startswith(('http://', 'https://')) and 'ebay' in url.lower():
                                if url not in urls:
                                    urls.append(url)
                                    added_count += 1
                            else:
                                invalid_count += 1
                        
                        if added_count > 0:
                            success, message = save_urls(urls)
                            if success:
                                msg = f"✅ Added {added_count} URLs!"
                                if invalid_count > 0:
                                    msg += f" ({invalid_count} invalid URLs skipped)"
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(message)
                        elif invalid_count > 0:
                            st.error(f"❌ {invalid_count} invalid URLs found. URLs must start with http:// or https:// and contain 'ebay'")
                        else:
                            st.info("No new URLs to add (all already exist)")
                    else:
                        st.error("Please enter URLs to add!")
        
        # Show current statistics for both keywords and URLs
        st.divider()
        col_stats1, col_stats2, col_stats3, col_stats4 = st.columns(4)
        with col_stats1:
            st.metric("Total Keywords", len(keywords))
        with col_stats2:
            st.metric("Total URLs", len(urls))
        with col_stats3:
            state = load_state()
            st.metric("Active Scans", len(state))
        with col_stats4:
            total_inputs = len(keywords) + len(urls)
            st.metric("Total Monitored", total_inputs)
    
    with tab2:
        st.header("📊 Scraper Dashboard")
        
        # Status overview with better styling
        st.subheader("🎯 System Overview")
        col1, col2, col3, col4 = st.columns(4)
        stats = get_scraper_stats()
        
        with col1:
            if scraper_status == "Running":
                st.markdown("""
                <div style="background: linear-gradient(135deg, #10b981, #065f46); padding: 1rem; border-radius: 10px; color: white; text-align: center;">
                    <h3>🟢 Running</h3>
                    <p>Scraper Active</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="background: linear-gradient(135deg, #ef4444, #991b1b); padding: 1rem; border-radius: 10px; color: white; text-align: center;">
                    <h3>🔴 Stopped</h3>
                    <p>Scraper Inactive</p>
                </div>
                """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #3b82f6, #1e40af); padding: 1rem; border-radius: 10px; color: white; text-align: center;">
                <h3>{stats['total_keywords']}</h3>
                <p>Keywords Monitored</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #8b5cf6, #5b21b6); padding: 1rem; border-radius: 10px; color: white; text-align: center;">
                <h3>{stats['total_urls']}</h3>
                <p>URLs Monitored</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            if stats['last_update']:
                hours_ago = int((datetime.now() - stats['last_update']).total_seconds() / 3600)
                last_activity = f"{hours_ago}h ago"
            else:
                last_activity = "Never"
            
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #f59e0b, #d97706); padding: 1rem; border-radius: 10px; color: white; text-align: center;">
                <h3>{last_activity}</h3>
                <p>Last Activity</p>
            </div>
            """, unsafe_allow_html=True)
        
        st.divider()
        
        # Current Search Inputs Display
        col_search1, col_search2 = st.columns(2)
        
        with col_search1:
            st.subheader("🔍 Current Keywords")
            keywords = load_keywords()
            if keywords:
                # Display keywords in a nice grid
                for keyword in keywords:
                    st.markdown(f"""
                    <div style="
                        background-color: #f0f9ff; 
                        border: 2px solid #0ea5e9; 
                        border-radius: 8px; 
                        padding: 0.8rem; 
                        margin: 0.3rem 0;
                        text-align: center;
                        font-weight: bold;
                        color: #0c4a6e;
                    ">
                        🔍 {keyword}
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ No keywords configured!")
        
        with col_search2:
            st.subheader("🔗 Current URLs")
            urls = load_urls()
            if urls:
                # Display URLs in a nice format
                for url in urls:
                    display_url = url[:50] + "..." if len(url) > 50 else url
                    st.markdown(f"""
                    <div style="
                        background-color: #eff6ff; 
                        border: 2px solid #3b82f6; 
                        border-radius: 8px; 
                        padding: 0.8rem; 
                        margin: 0.3rem 0;
                        font-weight: bold;
                        color: #1e40af;
                    ">
                        🔗 {display_url}
                        <br><small style="color: #64748b;">Full: {url}</small>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.warning("⚠️ No URLs configured!")
        
        # Overall status
        st.divider()
        total_inputs = len(keywords) + len(urls)
        if total_inputs == 0:
            st.error("❌ No search inputs configured! Please add keywords or URLs in the Search Input Management tab.")
        else:
            st.success(f"✅ Monitoring {len(keywords)} keywords and {len(urls)} URLs ({total_inputs} total search inputs)")
        
        st.divider()
        
        # Activity chart
        st.subheader("📈 Scanning Activity")
        chart = create_activity_chart()
        if chart:
            st.plotly_chart(chart, use_container_width=True)
        else:
            st.info("📊 No scanning data available yet. Start the scraper to see activity charts!")
        
        # Recent activity table
        st.subheader("📋 Recent Activity Log")
        state = load_state()
        if state:
            activity_data = []
            for keyword, timestamp in state.items():
                try:
                    dt = datetime.fromisoformat(timestamp)
                    time_ago = datetime.now() - dt
                    hours_ago = int(time_ago.total_seconds() / 3600)
                    status_icon = "🟢" if hours_ago < 24 else "🟡" if hours_ago < 48 else "🔴"
                    
                    activity_data.append({
                        'Keyword': keyword,
                        'Last Scan': dt.strftime('%Y-%m-%d %H:%M:%S'),
                        'Hours Ago': hours_ago,
                        'Status': f'{status_icon} {"Recent" if hours_ago < 24 else "Old" if hours_ago < 48 else "Very Old"}'
                    })
                except:
                    activity_data.append({
                        'Keyword': keyword,
                        'Last Scan': timestamp,
                        'Hours Ago': 'Unknown',
                        'Status': '⚪ Unknown'
                    })
            
            df = pd.DataFrame(activity_data)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("📝 No activity data available. The scraper hasn't run yet or state.json is empty.")
        
        # Quick Actions
        st.divider()
        st.subheader("⚡ Quick Actions")
        col_action1, col_action2, col_action3 = st.columns(3)
        
        with col_action1:
            if st.button("🔄 Refresh Data", type="secondary", use_container_width=True):
                st.rerun()
        
        with col_action2:
            if st.button("📊 View Keywords", type="secondary", use_container_width=True):
                st.info("Switch to the Keywords tab to manage your search terms.")
        
        with col_action3:
            if st.button("⚙️ Settings", type="secondary", use_container_width=True):
                st.info("Switch to the Settings tab for configuration options.")
    
    with tab3:
        st.header("⚙️ Scraper Settings")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🔧 Configuration")
            st.info("Advanced settings will be available in future updates.")
            
            # Polling interval (read-only for now)
            st.text_input("Poll Interval (seconds)", value="120", disabled=True, help="Time between scans")
            st.text_input("Max Pages per Keyword", value="1", disabled=True, help="Pages to scrape per keyword")
            
        with col2:
            st.subheader("📞 Telegram Settings")
            st.info("Telegram configuration is managed in the scraper file.")
              # Show current telegram settings (masked)
            st.text_input("Bot Token", value="*" * 20, disabled=True, type="password")
            st.text_input("Chat ID", value="*" * 10, disabled=True)
    
    with tab4:
        st.header("📋 System Logs & Process Information")
        
        # Process information section
        st.subheader("🔍 Process Information")
        col_proc1, col_proc2 = st.columns(2)
        
        with col_proc1:
            if scraper_status == "Running":
                process_info = st.session_state.scraper_manager.get_process_info()
                if process_info:
                    st.markdown(f"""
                    **Process Status:** � Running  
                    **PID:** {process_info['pid']}  
                    **Status:** {process_info.get('status', 'N/A')}  
                    """)
                    if 'cpu_percent' in process_info:
                        st.markdown(f"**CPU Usage:** {process_info['cpu_percent']:.1f}%")
                    if 'memory_info' in process_info:
                        memory_mb = process_info['memory_info'].rss / 1024 / 1024
                        st.markdown(f"**Memory Usage:** {memory_mb:.1f} MB")
                    if 'create_time' in process_info:
                        runtime = datetime.now() - process_info['create_time']
                        st.markdown(f"**Runtime:** {str(runtime).split('.')[0]}")
                else:
                    st.markdown("**Process Status:** 🟢 Running (details unavailable)")
            else:
                st.markdown("**Process Status:** 🔴 Stopped")
        
        with col_proc2:
            # File status
            st.markdown("**File Status:**")
            if PID_FILE.exists():
                st.markdown("📄 PID file exists")
            else:
                st.markdown("❌ No PID file")
            
            if LOG_FILE.exists():
                log_size = LOG_FILE.stat().st_size / 1024
                st.markdown(f"📄 Log file: {log_size:.1f} KB")
            else:
                st.markdown("❌ No log file")
        
        st.divider()
        
        # Logs section
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            st.subheader("📋 Real-time Logs")
        
        with col2:
            num_lines = st.selectbox("Lines to show:", [25, 50, 100, 200], index=1)
        
        with col3:
            if st.button("🔄 Refresh Logs", use_container_width=True):
                st.rerun()
        
        # Display real logs from file
        logs = get_recent_logs(num_lines)
        
        if logs and logs[0] != "No logs available yet.":
            # Create a container for logs with scroll
            log_container = st.container()
            with log_container:
                st.markdown("```")
                for log in logs[-20:]:  # Show last 20 for better performance
                    if any(keyword in log.upper() for keyword in ["ERROR", "FAILED", "EXCEPTION"]):
                        st.markdown(f"🔴 {log}")
                    elif any(keyword in log.upper() for keyword in ["WARNING", "WARN"]):
                        st.markdown(f"🟡 {log}")
                    elif any(keyword in log.upper() for keyword in ["SUCCESS", "STARTED", "COMPLETED"]):
                        st.markdown(f"🟢 {log}")
                    else:
                        st.markdown(f"ℹ️ {log}")
                st.markdown("```")
            
            # Show all logs in an expander
            with st.expander(f"📜 View all {len(logs)} log entries"):
                st.text("\n".join(logs))
        else:
            st.info("📝 No logs available yet. Start the scraper to see activity logs.")
            
            # Show some system info instead
            st.subheader("📊 System Information")
            keywords = load_keywords()
            current_time = datetime.now()
            
            sample_logs = [
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] INFO: Dashboard accessed",
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] INFO: Scraper status: {scraper_status}",
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] INFO: Monitoring {len(keywords)} keywords",
                f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] INFO: UI loaded successfully"
            ]
            
            for log in sample_logs:
                if "ERROR" in log or "WARNING" in log:
                    st.error(log)
                elif "INFO" in log:
                    st.info(log)
        
        # Auto-refresh for logs
        if st.checkbox("🔄 Auto-refresh logs (10s)", key="logs_auto_refresh"):
            time.sleep(10)
            st.rerun()
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #6b7280; padding: 1rem;'>
        <p>🛒 eBay Listing Scraper Dashboard v1.0 | Built with Streamlit</p>
        <p>Professional monitoring solution for eBay listings</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
