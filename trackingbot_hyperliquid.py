import requests
import time
import json
from datetime import datetime, timedelta
from threading import Thread

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "token telegram bot/not tgh ID"
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"

# Data storage 
user_subscriptions = {}  
position_state = {}  
last_daily_update = {}  

CHECK_INTERVAL = 30
UPDATE_HOURS = [0, 12]  

# --- TELEGRAM FUNCTIONS ---

def send_message(chat_id, text):
    """Send a message to a specific chat."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "disable_notification": False  
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json().get("ok", False)
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def get_updates(offset=None):
    """Get new messages from Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 30, "offset": offset}
    
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json().get("result", [])
    except Exception as e:
        print(f"Error getting updates: {e}")
        return []

# --- HYPERLIQUID FUNCTIONS ---

def get_positions(address):
    """Fetch all open positions for an address."""
    payload = {"type": "clearinghouseState", "user": address}
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(HYPERLIQUID_API, json=payload, headers=headers, timeout=10)
        data = response.json()
        positions = {}
        
        if "assetPositions" in data:
            for item in data["assetPositions"]:
                try:
                    pos = item["position"]
                    coin = pos.get("coin")

                    if not coin:
                        continue
                    
                    size_str = pos.get("szi", "0")
                    size = float(size_str) if size_str is not None else 0.0
                    
                    # Only include non-zero positions
                    if size != 0:
                        entry_px = pos.get("entryPx", "0")
                        unrealized_pnl = pos.get("unrealizedPnl", "0")
                        liq_px = pos.get("liquidationPx", "0")
                        margin_used = pos.get("marginUsed", "0")
                        
                        leverage_data = pos.get("leverage", {})
                        if isinstance(leverage_data, dict):
                            leverage = leverage_data.get("value", "1")
                        else:
                            leverage = str(leverage_data) if leverage_data else "1"
                        
                        positions[coin] = {
                            "size": size,
                            "entry": float(entry_px) if entry_px is not None else 0.0,
                            "pnl": float(unrealized_pnl) if unrealized_pnl is not None else 0.0,
                            "leverage": leverage,
                            "side": "LONG" if size > 0 else "SHORT",
                            "liq_price": float(liq_px) if liq_px is not None and liq_px != "0" else 0.0,
                            "margin": float(margin_used) if margin_used is not None else 0.0
                        }
                except (ValueError, TypeError, KeyError) as e:
                    print(f"Error parsing position data for {address}: {e}")
                    continue
        
        return positions
        
    except Exception as e:
        print(f"Error fetching {address}: {e}")
        return None

def format_address(address):
    """Shorten address for display."""
    return f"{address[:6]}...{address[-4:]}"

# --- BOT COMMAND HANDLERS ---

def handle_start(chat_id):
    """Handle /start command."""
    msg = (
        "🤖 *Hyperliquid Position Monitor Bot*\n\n"
        "Track any trader's positions and get instant alerts!\n\n"
        "*Commands:*\n"
        "`/add 0x...` - Add address to monitor\n"
        "`/remove 0x...` - Stop monitoring address\n"
        "`/list` - Show your monitored addresses\n"
        "`/status` - Check positions now\n"
        "`/help` - Show this message\n\n"
        "Example:\n"
        "`/add 0x1234567890abcdef1234567890abcdef12345678`\n\n"
        "*You'll get alerts with:*\n"
        "• Position side (LONG/SHORT)\n"
        "• Leverage used (e.g. 5x, 10x)\n"
        "• Entry price & size\n"
        "• Liquidation price\n"
        "• Real-time PnL"
    )
    send_message(chat_id, msg)

def handle_add(chat_id, address):
    """Add an address to user's watchlist."""
    # Validate address format
    if not address.startswith("0x") or len(address) != 42:
        send_message(chat_id, "❌ Invalid address format. Must be 42 characters starting with 0x")
        return
    
    if chat_id not in user_subscriptions:
        user_subscriptions[chat_id] = []
    
    if address in user_subscriptions[chat_id]:
        send_message(chat_id, f"⚠️ Already monitoring:\n`{address}`")
        return
    
    # Add address
    user_subscriptions[chat_id].append(address)
    
    if address not in position_state:
        fetched_positions = get_positions(address)
        position_state[address] = fetched_positions if fetched_positions is not None else {}
    
    msg = (
        f"✅ *Now Monitoring*\n"
        f"Address: `{address}`\n"
        f"Short: `{format_address(address)}`\n\n"
        f"You'll receive alerts for:\n"
        f"• New positions opened (with leverage)\n"
        f"• Positions closed (with final PnL)\n"
        f"• Position summaries every 12 hours (00:00 and 12:00)"
    )
    send_message(chat_id, msg)
    
    # Show current positions if any
    positions = position_state[address]
    if positions:
        msg = f"📊 *Current Positions:*\n\n"
        for coin, pos in positions.items():
            msg += f"*{coin}/USD* - {pos['side']} {pos['leverage']}x\n"
            msg += f"Size: {abs(pos['size']):.4f} {coin}\n"
            msg += f"Entry: ${pos['entry']:,.2f}\n"
            msg += f"PnL: ${pos['pnl']:,.2f}\n"
            if pos['liq_price'] > 0:
                msg += f"Liq: ${pos['liq_price']:,.2f}\n\n"
            else:
                msg += f"Liq: N/A\n\n"
        send_message(chat_id, msg)

def handle_remove(chat_id, address):
    """Remove an address from watchlist."""
    if chat_id not in user_subscriptions or address not in user_subscriptions[chat_id]:
        send_message(chat_id, f"❌ Not monitoring this address:\n`{address}`")
        return
    
    user_subscriptions[chat_id].remove(address)
    
    if not user_subscriptions[chat_id]:
        del user_subscriptions[chat_id]
    
    send_message(chat_id, f"✅ Stopped monitoring:\n`{format_address(address)}`")

def handle_list(chat_id):
    """List all monitored addresses for this user."""
    if chat_id not in user_subscriptions or not user_subscriptions[chat_id]:
        send_message(chat_id, "📭 You're not monitoring any addresses.\n\nUse `/add 0x...` to start!")
        return
    
    msg = f"📋 *Your Monitored Addresses:*\n\n"
    for i, addr in enumerate(user_subscriptions[chat_id], 1):
        positions_count = len(position_state.get(addr, {}))
        msg += f"{i}. `{format_address(addr)}`\n"
        msg += f"   Open positions: {positions_count}\n\n"
    
    msg += f"Total: {len(user_subscriptions[chat_id])} addresses"
    send_message(chat_id, msg)

def handle_status(chat_id):
    """Show current status of all monitored addresses."""
    if chat_id not in user_subscriptions or not user_subscriptions[chat_id]:
        send_message(chat_id, "📭 You're not monitoring any addresses.")
        return
    
    for address in user_subscriptions[chat_id]:
        positions = position_state.get(address, {})
        
        if not positions:
            msg = f"📊 `{format_address(address)}`\n\nNo open positions"
        else:
            total_pnl = sum(p["pnl"] for p in positions.values())
            msg = f"📊 `{format_address(address)}`\n"
            msg += f"Open: {len(positions)} | Total PnL: ${total_pnl:,.2f}\n\n"
            
            for coin, pos in positions.items():
                pnl_emoji = "🟢" if pos["pnl"] >= 0 else "🔴"
                msg += f"{pnl_emoji} *{coin}/USD* {pos['side']} *{pos['leverage']}x*\n"
                msg += f"Size: {abs(pos['size']):.4f} | Entry: ${pos['entry']:,.2f}\n"
                msg += f"PnL: ${pos['pnl']:,.2f}"
                if pos['liq_price'] > 0:
                    msg += f" | Liq: ${pos['liq_price']:,.2f}\n\n"
                else:
                    msg += f" | Liq: N/A\n\n"
        
        send_message(chat_id, msg)

def process_command(chat_id, text):
    """Process incoming bot commands."""
    parts = text.strip().split(maxsplit=1)
    command = parts[0].lower()
    
    if command == "/start" or command == "/help":
        handle_start(chat_id)
    elif command == "/add":
        if len(parts) < 2:
            send_message(chat_id, "❌ Usage: `/add 0x1234...`")
        else:
            handle_add(chat_id, parts[1].strip())
    elif command == "/remove":
        if len(parts) < 2:
            send_message(chat_id, "❌ Usage: `/remove 0x1234...`")
        else:
            handle_remove(chat_id, parts[1].strip())
    elif command == "/list":
        handle_list(chat_id)
    elif command == "/status":
        handle_status(chat_id)
    else:
        send_message(chat_id, "❌ Unknown command. Send /help for available commands.")

# --- MONITORING FUNCTIONS ---

def check_positions_for_subscribers(address):
    """Check position changes and notify all subscribers of this address."""
    current_positions = get_positions(address)
    
    if current_positions is None:
        return
    
    old_positions = position_state.get(address, {})
    
    # Find all users monitoring this address
    subscribers = [chat_id for chat_id, addrs in user_subscriptions.items() if address in addrs]
    
    # Check for new positions
    for coin, pos in current_positions.items():
        if coin not in old_positions:
            # Calculate position value
            position_value = abs(pos['size']) * pos['entry']
            
            msg = (f"🚨 *NEW POSITION OPENED*\n"
                   f"Address: `{format_address(address)}`\n\n"
                   f"📈 *{coin}/USD* - {pos['side']}\n"
                   f"⚡ *Leverage: {pos['leverage']}x*\n\n"
                   f"Size: `{abs(pos['size']):.4f}` {coin}\n"
                   f"Value: `${position_value:,.2f}`\n"
                   f"Entry: `${pos['entry']:,.2f}`\n")
            
            if pos['liq_price'] > 0:
                msg += f"💀 Liq: `${pos['liq_price']:,.2f}`"
            else:
                msg += f"💀 Liq: N/A"
            
            for chat_id in subscribers:
                send_message(chat_id, msg)
    
    # Check for closed positions
    for coin, old_pos in old_positions.items():
        if coin not in current_positions:
            pnl_emoji = "💰" if old_pos['pnl'] >= 0 else "💸"
            pnl_text = "PROFIT" if old_pos['pnl'] >= 0 else "LOSS"
            
            msg = (f"{pnl_emoji} *POSITION CLOSED - {pnl_text}*\n"
                   f"Address: `{format_address(address)}`\n\n"
                   f"📉 *{coin}/USD* - {old_pos['side']}\n"
                   f"⚡ Leverage: {old_pos['leverage']}x\n\n"
                   f"Entry: `${old_pos['entry']:,.2f}`\n"
                   f"Size: `{abs(old_pos['size']):.4f}` {coin}\n"
                   f"Final PnL: `${old_pos['pnl']:,.2f}`")
            
            for chat_id in subscribers:
                send_message(chat_id, msg)
    
    # Check for leverage changes 
    for coin in current_positions:
        if coin in old_positions:
            old_size = abs(old_positions[coin]['size'])
            new_size = abs(current_positions[coin]['size'])
            
            # Avoid division by zero
            if old_size > 0:
                size_change_pct = abs(new_size - old_size) / old_size * 100
                
                # Alert if size changed by more than 10%
                if size_change_pct > 10:
                    action = "INCREASED" if new_size > old_size else "DECREASED"
                    pos = current_positions[coin]
                    
                    msg = (f"⚠️ *POSITION {action}*\n"
                           f"Address: `{format_address(address)}`\n\n"
                           f"*{coin}/USD* {pos['side']} {pos['leverage']}x\n"
                           f"Old Size: `{old_size:.4f}` → New Size: `{new_size:.4f}`\n"
                           f"Change: `{size_change_pct:.1f}%`\n"
                           f"Current PnL: `${pos['pnl']:,.2f}`")
                    
                    for chat_id in subscribers:
                        send_message(chat_id, msg)
    
    # Update state
    position_state[address] = current_positions

def send_summary_to_subscribers(address):
    """Send 12-hour summary to all subscribers of this address."""
    positions = position_state.get(address, {})
    subscribers = [chat_id for chat_id, addrs in user_subscriptions.items() if address in addrs]
    
    if not positions:
        msg = f"📅 *12-Hour Update*\n`{format_address(address)}`\n\nNo open positions"
    else:
        total_pnl = sum(p["pnl"] for p in positions.values())
        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
        
        msg = f"📅 *12-Hour Update*\n`{format_address(address)}`\n\n"
        msg += f"{pnl_emoji} Open: {len(positions)} | Total PnL: *${total_pnl:,.2f}*\n\n"
        
        for coin, pos in positions.items():
            pnl_emoji = "🟢" if pos["pnl"] >= 0 else "🔴"
            msg += f"{pnl_emoji} *{coin}/USD* {pos['side']} *{pos['leverage']}x*\n"
            msg += f"  Size: `{abs(pos['size']):.4f}` {coin}\n"
            msg += f"  Entry: `${pos['entry']:,.2f}`\n"
            msg += f"  PnL: `${pos['pnl']:,.2f}`"
            if pos['liq_price'] > 0:
                msg += f" | Liq: `${pos['liq_price']:,.2f}`\n\n"
            else:
                msg += f" | Liq: N/A\n\n"
    
    for chat_id in subscribers:
        key = f"{chat_id}_{address}"
        send_message(chat_id, msg)
        last_daily_update[key] = datetime.now()

def should_send_update(chat_id, address):
    """Check if 12-hour update should be sent."""
    key = f"{chat_id}_{address}"
    now = datetime.now()
    
    if key not in last_daily_update:
        last_daily_update[key] = now - timedelta(days=1)
    
    last_sent = last_daily_update[key]
    return (now.hour in UPDATE_HOURS and (now - last_sent).total_seconds() >= 12 * 3600)

# --- MAIN LOOPS ---

def monitoring_loop():
    """Background thread that monitors positions."""
    print("📊 Monitoring loop started")
    
    while True:
        try:
            # Get unique addresses being monitored
            all_addresses = set()
            for addrs in user_subscriptions.values():
                all_addresses.update(addrs)
            
            # Check each address
            for address in all_addresses:
                check_positions_for_subscribers(address)
                
                # Check if daily update needed
                if datetime.now().hour in UPDATE_HOURS:
                    subscribers = [chat_id for chat_id, addrs in user_subscriptions.items() if address in addrs]
                    for chat_id in subscribers:
                        if should_send_update(chat_id, address):
                            send_summary_to_subscribers(address)
                            break  
                
                time.sleep(1)  
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            time.sleep(60)

def bot_loop():
    """Main bot loop for handling commands."""
    print("🤖 Bot loop started")
    offset = None
    
    while True:
        try:
            updates = get_updates(offset)
            
            for update in updates:
                offset = update["update_id"] + 1
                
                if "message" in update:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    text = message.get("text", "")
                    
                    if text.startswith("/"):
                        print(f"Command from {chat_id}: {text}")
                        process_command(chat_id, text)
                        
        except KeyboardInterrupt:
            print("\n⚠️ Bot stopped by user")
            break
        except Exception as e:
            print(f"Error in bot loop: {e}")
            time.sleep(5)

# --- MAIN ---

if __name__ == "__main__":
    print("🚀 Starting Multi-User Hyperliquid Monitor Bot")
    print(f"Check interval: {CHECK_INTERVAL}s")
    print(f"Updates every 12 hours at: {UPDATE_HOURS}\n")
    
    # Start monitoring in background thread
    monitor_thread = Thread(target=monitoring_loop, daemon=True)
    monitor_thread.start()
    
    # Run bot command handler in main thread
    bot_loop()
