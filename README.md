# Your Sprouts

A phone-friendly app for selling **sprout packets**.

- **Administrator** creates vendors and sees the full activity history.
- **Vendors** add customers, set each customer's **price per packet**, record packets delivered each day, mark months paid/unpaid, and answer customer requests.
- **Customers** record how many packets they received each day, see their monthly statement, accept or reject price changes, and send requests.

Works in **English and Telugu** (choose on the first screen, switch anytime with the button at the top) and can be **installed on a phone like an app**.

---

## Files in this folder (all loose, no sub-folders)

| File | What it is |
|---|---|
| `app.py` | The main program (all the logic) |
| `translations.py` | Every word on screen in English and Telugu. Edit here to change wording |
| `*.html` | The screens |
| `style.css` | Colours and layout |
| `app.js` | Small phone helpers (+/− buttons, copy, install button) |
| `sw.js`, `manifest.json`, `icon-*.png`, `favicon.png` | What makes it installable as a phone app |
| `requirements.txt` | Tells Render what to install |

---

## Put it online (step by step)

### 1. Upload to GitHub
1. Go to github.com → **New repository** → name it `your-sprouts` → **Private** → Create.
2. Click **uploading an existing file**, drag in **all the files** from this folder, then **Commit changes**.

### 2. Create the app on Render
1. Go to render.com → **New +** → **Web Service** → pick the `your-sprouts` repository.
2. Fill in:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
3. Under **Environment Variables**, add these three:

| Key | Value |
|---|---|
| `SECRET_KEY` | Any long random text, e.g. `k8Zq...` (40+ characters). Keep it private |
| `ADMIN_SECRET` | Your own administrator Secret ID, e.g. `SPROUT-ADMIN-2026`. This is what **you** type to log in as administrator |
| `DB_PATH` | `/var/data/sprouts.db` (only if you add a disk, see step 4) |

4. **Important: keep your data safe.** On Render's free plan, the data file is wiped every time the app restarts or you upload new code. To keep data permanently, choose a paid instance and add a **Disk** (Settings → Disks → mount path `/var/data`, 1 GB is plenty), then set `DB_PATH` as above.
5. Click **Create Web Service**. After a few minutes you get a link like `your-sprouts.onrender.com`.

### 3. Use your own domain (optional)
On Render: **Settings → Custom Domains → Add**, e.g. `sprouts.bhadragirimart.com`. Render shows a **CNAME** value.
On Hostinger: **Domains → DNS / Nameservers → Add record** → Type `CNAME`, Name `sprouts`, Target = the value Render gave. Wait up to an hour.

### 4. First use
1. Open the link → choose language → log in with your `ADMIN_SECRET`.
2. **Add a vendor** → the app shows their Secret ID **once**. Send it to them.
3. The vendor logs in → **Customers → Add a customer** (name, mobile, price per packet) → shares the customer's Secret ID.
4. On a phone, open the link in Chrome → tap **Install app** (or menu → *Add to Home screen*).

---

## Decision register

Rules built into the app. ✅ = you decided. ❓ = I chose a sensible default — **please confirm or tell me to change it.**

| # | Rule | Status |
|---|---|---|
| 1 | App name: **Your Sprouts**; product is counted in **packets** | ✅ |
| 2 | Three levels: Administrator → Vendors → Customers | ✅ |
| 3 | Each customer has their own price per packet, set by their vendor | ✅ |
| 4 | Login by random Secret ID only (no OTP). Admin gives vendors theirs; vendors give customers theirs | ✅ |
| 5 | Secret IDs can never be viewed again, only **reset** (old one stops working) | ✅ |
| 6 | Customers make no payments in the app; vendor just marks months Paid/Unpaid | ✅ |
| 7 | English + Telugu, chosen at start, switchable anytime. ₹ currency | ✅ |
| 8 | Installable on phones; hosted on Render; domain from Hostinger | ✅ |
| 9 | **Both sides record packets:** customer enters "received", vendor enters "delivered"; the app shows ✓ match or ⚠ mismatch | ❓ |
| 10 | **The bill uses the customer's count.** If the customer didn't enter a day, the vendor's count is used | ❓ |
| 11 | **Price changes need the customer's approval.** Vendor sets new price + start date (today or later); it applies only after the customer taps Accept. If rejected, the old price stays | ❓ |
| 12 | When a month is marked **Paid**, it is locked: nobody can change entries in that month (vendor can mark Unpaid to unlock) | ❓ |
| 13 | Customers can enter any past date (not future dates) and correct their own entry until the month is paid | ❓ |
| 14 | Customer requests are free text (e.g. "extra packets Sunday"); vendor can reply and mark done | ❓ |
| 15 | Deactivating a vendor also blocks all their customers from logging in | ❓ |
| 16 | 10 wrong Secret ID attempts → that device waits 15 minutes | ❓ |
| 17 | The administrator sees the activity history for everyone; vendors and customers don't see it | ❓ |
| 18 | No email anywhere: customers are added with name, mobile and price only | ✅ |
| 19 | When new files are uploaded, phones show **"New version available – tap to update"** (checked when the app is opened, and every 30 minutes) | ✅ |
| 20 | Telugu wording was written by me — a native speaker should read it once and correct it in `translations.py` | ❓ |
