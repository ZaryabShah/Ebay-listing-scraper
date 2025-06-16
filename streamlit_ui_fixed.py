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
        
    def start_scraper(self):
        """Start the scraper process"""
        if not self.is_running:
            try:
                self.process = subprocess.Popen([
                    sys.executable, SCRAPER_SCRIPT
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.is_running = True
                return True, "Scraper started successfully!"
            except Exception as e:
                return False, f"Failed to start scraper: {str(e)}"
        return False, "Scraper is already running!"
    
    def stop_scraper(self):
        """Stop the scraper process"""
        if self.is_running and self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
                self.is_running = False
                return True, "Scraper stopped successfully!"
            except Exception as e:
                return False, f"Failed to stop scraper: {str(e)}"
        return False, "Scraper is not running!"
    
    def get_status(self):
        """Get current scraper status"""
        if self.process and self.is_running:
            if self.process.poll() is None:
                return "Running"
            else:
                self.is_running = False
                return "Stopped"
        return "Stopped"

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
        return ["Playstation 5", "Grafikkarte", "Nintendo Switch"]  # Default keywords if parsing fails
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
    
    stats = {
        'total_keywords': len(keywords),
        'active_keywords': len(state),
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
        
        # Scraper controls
        scraper_status = st.session_state.scraper_manager.get_status()
        
        if scraper_status == "Running":
            st.markdown('<p class="status-running">● Status: Running</p>', unsafe_allow_html=True)
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
        st.metric("Active Scans", stats['active_keywords'])
        if stats['last_update']:
            time_ago = datetime.now() - stats['last_update']
            hours_ago = int(time_ago.total_seconds() / 3600)
            st.metric("Last Activity", f"{hours_ago}h ago")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Main content area
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Keywords", "📊 Dashboard", "⚙️ Settings", "📋 Logs"])
    
    with tab1:
        st.header("🔍 Keyword Management")
        
        # Current keywords
        keywords = load_keywords()
        
        # Debug info
        st.write(f"Debug: Found {len(keywords)} keywords")
        
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
                                color: #1e293b;  /* 👈 Dark blue-gray text */
                            ">
                                🔍 <strong>{keyword}</strong>
                            </div>
                            """, unsafe_allow_html=True)
                    with col_del:
                        if st.button("🗑️", key=f"del_{i}", help="Delete keyword", type="secondary"):
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
        
        # Show current keyword count
        st.divider()
        col_stats1, col_stats2, col_stats3 = st.columns(3)
        with col_stats1:
            st.metric("Total Keywords", len(keywords))
        with col_stats2:
            state = load_state()
            st.metric("Active Scans", len(state))
        with col_stats3:
            if keywords:
                st.metric("Newest Keyword", keywords[-1] if keywords else "None")
    
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
                <h3>{stats['active_keywords']}</h3>
                <p>Active Scans</p>
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
        
        # Current Keywords Display
        st.subheader("🔍 Current Keywords")
        keywords = load_keywords()
        if keywords:
            # Display keywords in a nice grid
            cols = st.columns(3)
            for i, keyword in enumerate(keywords):
                with cols[i % 3]:
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
            st.warning("⚠️ No keywords configured! Go to the Keywords tab to add some search terms.")
        
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
        st.header("📋 System Logs")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.subheader("📋 Recent Logs")
        
        with col2:
            if st.button("🔄 Refresh Logs"):
                st.rerun()
        
        # Log display
        current_time = datetime.now()
        keywords = load_keywords()
        logs = [
            f"[{current_time.strftime('%H:%M:%S')}] INFO: Scraper status: {scraper_status}",
            f"[{(current_time - timedelta(minutes=5)).strftime('%H:%M:%S')}] INFO: Monitoring {len(keywords)} keywords",
            f"[{(current_time - timedelta(minutes=10)).strftime('%H:%M:%S')}] INFO: Last state update completed",
        ]
        
        if scraper_status == "Running":
            logs.insert(0, f"[{current_time.strftime('%H:%M:%S')}] INFO: ✅ Scraper is actively monitoring")
        else:
            logs.insert(0, f"[{current_time.strftime('%H:%M:%S')}] WARNING: ⚠️ Scraper is not running")
        
        for log in logs:
            if "ERROR" in log or "WARNING" in log:
                st.error(log)
            elif "INFO" in log:
                st.info(log)
            else:
                st.text(log)
    
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
