# De-Anza-College-Course-Monitor

An automated command-line course sniper for De Anza College students. This script continuously monitors the De Anza schedule of classes for specific Course Reference Numbers (CRNs). When a targeted class transitions to "OPEN" or "WAITLIST", it instantly notifies you via email so you can secure your spot.

## ✨ Features
* **Interactive CLI**: Easy-to-use startup wizard to configure your target Department, Term, and CRNs right from the terminal.
* **Vivid Console Output**: Color-coded, real-time logging to track scraping attempts, statuses, and sleep intervals.
* **Smart Scraping**: Utilizes `BeautifulSoup4` with dual-strategy parsing (exact class name matching + fallback regex) to ensure you don't miss an opening even if the HTML structure slightly shifts.
* **Anti-Bot Jitter**: Implements randomized request delays to mimic human traffic and prevent IP blocking.
* **Instant Email Alerts**: Integration with the Mailgun API for reliable, instant delivery to primary and backup email addresses.
* **Robust Scheduling**: Powered by `apscheduler` to run consistently at 15-second intervals with built-in fault tolerance.

## 🛠️ Prerequisites
* Python 3.8+
* A [Mailgun](https://www.mailgun.com/) account (Sandbox or Custom Domain) for sending emails.

## 🚀 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/yourusername/deanza-course-sniper.git](https://github.com/yourusername/deanza-course-sniper.git)
   cd deanza-course-sniper
