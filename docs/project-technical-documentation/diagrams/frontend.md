# Frontend diagrams

[← Back to index](../README.md) · Details: [04 — Frontend documentation](../04-frontend-documentation.md)

## Route tree (`frontend/src/main.jsx::App`)

```mermaid
flowchart TD
  App["App → AuthProvider → BrowserRouter"] --> L["/ → Landing"]
  App --> TP["/test-payment/:token → TestPaymentPage (no auth)"]
  App --> LG["/login → AuthPage"]
  App --> RG["/register → AuthPage register"]
  App --> PR["/rider/* → Protected role=rider"]
  App --> PD["/driver/* → Protected role=driver"]
  App --> PA["/admin/* → Protected role=admin"]
  App --> NF["* → 'Wrong turn?' page"]
  PR & PD & PA --> WS["Workspace (sidebar + nested Routes)"]
  WS --> IDX["index → RideWorkspace view=overview"]
  WS --> H["history (rider, driver) → RideWorkspace view=history"]
  WS --> E["earnings (driver) → RideWorkspace view=earnings"]
  WS --> DR["drivers, rides (admin) → RideWorkspace"]
  WS --> FS["settings (admin) → FareSettings"]
  WS --> RV["revenue (admin) → RevenueSettings"]
  WS --> AU["audit (admin) → AdminAudit"]
  WS --> AC["account → Account"]
  WS --> CS["* → ComingSoon"]
```

## Component tree of `RideWorkspace`

```mermaid
flowchart TD
  RW["RideWorkspace<br/>useWorkspace · useDriverLocation · usePaymentPrompt · usePaymentConfirmedFlash"]
  RW --> CN["CancellationNotice (recent_cancellation)"]
  RW --> BP["BookingPanel (rider, no active ride)"]
  BP --> GRM1["GoogleRouteMap (picker)"]
  BP --> ADS["AddressSearch ×2"]
  BP --> QD1["QuoteDetails"]
  RW --> ARP["ActiveRidePanel (active_ride)"]
  ARP --> TSC["TripStatsCard"]
  ARP --> RC["RideCard"]
  ARP --> TRM["TripRouteMap → GoogleRouteMap (read-only)"]
  RC --> ARD["AssignedRideDetails"]
  RC --> OTP["OtpInput (driver, WAITING)"]
  RC --> CRC["CancelRideControl"]
  RC --> PSL["PaymentStatusLine"]
  RC --> RF["RatingForm (compact)"]
  RC --> TPC["TestPaymentCard"]
  RW --> DCC["DriverCollectCard ×n (driver)"]
  RW --> PCF["PaymentConfirmedFlash (driver)"]
  RW --> DM["DriverManagement (admin)"]
  DM --> VE["VehicleEditor"]
  RW --> PP["PaymentPrompt (rider modal)"]
  PP --> RF2["RatingForm"]
```

## Shared modules

```mermaid
flowchart LR
  components["All components"] --> api["api.js"]
  api --> auth["authSession.js<br/>(session, refresh, signIn, signOut)"]
  main["main.jsx AuthProvider"] --> auth
  ADS["AddressSearch"] --> gm["googleMaps.js loadMaps()"]
  GRM["GoogleRouteMap"] --> gm
  RW["RideWorkspace"] --> loc["useDriverLocation.js"]
  BP["BookingPanel"] --> loc
  loc --> api
```
