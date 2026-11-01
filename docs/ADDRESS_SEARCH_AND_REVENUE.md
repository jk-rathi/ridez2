# Address search and revenue sharing

## Update your local installation

Stop both servers. From the repository root:

```powershell
git pull --ff-only
cd backend
.\.venv312\Scripts\python.exe -m flask --app run db upgrade
.\.venv312\Scripts\python.exe run.py
```

In the second terminal, from the repository root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

No new keys or packages are required for this update. Your existing environment files, accounts, trips, and allocations are preserved. A database migration adds revenue settings and allocation version/timestamp fields; existing allocations remain version 0 with their original percentages and amounts.

## Enable Google address suggestions

1. Select your existing Google Cloud project.
2. Open **APIs & Services → Library**, search for **Places API (New)**, and enable it.
3. Open **Credentials → your browser key → API restrictions**. Allow **both Maps JavaScript API and Places API (New)**.
4. Keep **Application restrictions → Websites** and your existing localhost website entries. Do not replace website restrictions with IP restrictions on the browser key.
5. Keep the working backend Routes API key unchanged. The backend does not use Places search.
6. Save, allow changes to propagate, and reload the website. No key-value change is needed. Restart Vite if you edit a frontend environment file.

Open `http://localhost:5173`, sign in as rider, and type at least three characters in **Pickup location** or **Destination**. Google suggestions appear inside the form. Click one, or use Arrow Down/Up and Enter. Escape closes the list. The chosen formatted address and coordinates update the map automatically. You can then request a fare without manually entering coordinates.

Editing a selected address clears its coordinates and any prior quote. Select a new suggestion or map point before requesting another fare. This prevents a displayed address from being routed to the previous selected position. Map clicks and **Use my location** remain available. Manual coordinates are tucked under **Coordinates and manual adjustment**. Simulator mode does not call Places and keeps explicit test-coordinate entry.

The search uses the new Maps JavaScript Places `AutocompleteSuggestion` interface, debounced requests, separate session tokens per address field, minimal selected-place fields (`formattedAddress`, `location`), Google attribution, and suppression of late responses after a newer query. Search failures show an error instead of assigning fabricated coordinates. Places requests can be billable; configure project quotas/budget alerts and check current Google pricing. Budget alerts are not spending caps.

If maps work but suggestions fail, check that Places API (New) is enabled **in the project owning the browser key** and included in that key's API restrictions. Allow time for changes to propagate. Do not put the server key in frontend variables or share either key in chat.

## Configure revenue allocation

As admin, open **Revenue share** in the sidebar.

- Default is **85% driver / 15% company**.
- Both percentages must be between 0 and 100, support two decimals, and sum to exactly 100.
- Enter a required change reason and save immediately, or choose a future effective date/time up to one year ahead.
- The date picker uses your browser timezone; the API stores UTC. Naive timestamps and backdated changes are rejected.
- A scheduled change does not activate early. For two versions with exactly the same effective timestamp, the newest version wins. Existing future schedules remain in force after an immediate change; review them before saving.
- Refresh/reopen the settings page to see a newly activated schedule. Every version is retained; the UI shows the latest 100 history/scheduled records, including admin ID, reason, save/effective times, new split, and split active when the change was saved.

The split **effective at server-side trip completion** is recorded with the settlement, not the split effective at quote/booking time. Driver allocation is rounded once to two decimals with half-up rounding; company allocation is the remaining eligible fare. They always sum to the eligible fare, including for small amounts, 100/0 and 0/100 splits. Repeated completion returns the original allocation and cannot reprice it or create a second ledger entry. Past allocations remain unchanged after later settings edits.

Eligible fare currently means the confirmed total including any surge. Taxes, tips, discounts, refunds, payment gateway fees and cancellation charges are not implemented. Allocation is an accounting record, not a payout or bank transfer. The driver earnings screen displays the percentage saved for each trip, rather than assuming every trip uses 85%.

## Verify locally

1. Search and select both addresses using the input suggestions. Check that markers move and a new route/fare uses those coordinates.
2. Edit one selected address without choosing a suggestion. Confirm the old quote disappears and booking is blocked until a location is selected again.
3. As admin, save an 80/20 split with a reason. Complete a trip and check the driver receives 80% in the ledger/earnings view.
4. Change the split to 90/10. Verify the earlier trip remains 80/20. New completions use 90/10.
5. Schedule another split for later. Verify it appears under upcoming changes and leaves the current allocation unchanged until its effective time.

Cloud browser checks use explicit Places/Routes fixtures to validate interaction, keyboard selection, stale results, errors and the complete trip/revenue flow. They do not exercise your Google billing project or live Places key restrictions. Those are verified locally after enabling the API. SQL Server integration and production multi-server deployment remain separate checks.
