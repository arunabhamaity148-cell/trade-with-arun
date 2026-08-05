# OrderFlow Analysis Pro — বাংলা গাইড (বিগিনারদের জন্য সম্পূর্ণ ব্যাখ্যা)

> এটি একটি **রিয়েল-টাইম অর্ডারফ্লো ট্রেডিং অ্যানালাইসিস সিস্টেম**। সহজ কথায় — এটি এমন একটি সফটওয়্যার যা মার্কেটের প্রতিটি ছোট ছোট লেনদেন (tick) বিশ্লেষণ করে বুঝতে পারে বড় বড় ট্রেডাররা কী করছেন, এবং সেই অনুযায়ী ট্রেড করার জন্য সিগন্যাল দেয়। এটি তৈরি করা হয়েছে **Fabio Testa-র মেথডলজি**-র উপর ভিত্তি করে।

[![Python](https://img.shields.io/badge/python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](.)
[![License](https://img.shields.io/badge/license-MIT-informational?style=for-the-badge)](LICENSE)
[![Instruments](https://img.shields.io/badge/instruments-29-blue?style=for-the-badge)](.)
[![Lines](https://img.shields.io/badge/code-~12,000-brightgreen?style=for-the-badge)](.)
[![API](https://img.shields.io/badge/API-16%20endpoints-orange?style=for-the-badge)](.)

---

## 📑 সূচিপত্র (Table of Contents)

- [১. অর্ডারফ্লো অ্যানালাইসিস কী? (একদম শুরু থেকে)](#১-অর্ডারফ্লো-অ্যানালাইসিস-কী-একদম-শুরু-থেকে)
- [২. সিস্টেমের সংক্ষিপ্ত পরিচিতি](#২-সিস্টেমের-সংক্ষিপ্ত-পরিচিতি)
- [৩. সিস্টেমের আর্কিটেকচার (কীভাবে কাজ করে)](#৩-সিস্টেমের-আর্কিটেকচার-কীভাবে-কাজ-করে)
- [৪. ৫টি মূল প্যাটার্ন ডিটেক্টর](#৪-৫টি-মূল-প্যাটার্ন-ডিটেক্টর)
- [৫. ভলিউম প্রোফাইল ফ্রেমিং (দৈনিক দিক নির্ধারণ)](#৫-ভলিউম-প্রোফাইল-ফ্রেমিং-দৈনিক-দিক-নির্ধারণ)
- [৬. স্টেট মেশিন ট্রেড লাইফসাইকেল](#৬-স্টেট-মেশিন-ট্রেড-লাইফসাইকেল)
- [৭. সাপোর্টেড ইনস্ট্রুমেন্ট (২৯টি)](#৭-সাপোর্টেড-ইনস্ট্রুমেন্ট-২৯টি)
- [৮. ডেটা সোর্স (MT5 + Bybit)](#৮-ডেটা-সোর্স-mt5--bybit)
- [৯. ড্যাশবোর্ড](#৯-ড্যাশবোর্ড)
- [১০. টেলিগ্রাম অ্যালার্ট](#১০-টেলিগ্রাম-অ্যালার্ট)
- [১১. ডেটাবেস](#১১-ডেটাবেস)
- [১২. ইনস্টলেশন (ধাপে ধাপে)](#১২-ইনস্টলেশন-ধাপে-ধাপে)
- [১৩. কনফিগারেশন](#১৩-কনফিগারেশন)
- [১৪. ব্যবহার পদ্ধতি](#১৪-ব্যবহার-পদ্ধতি)
- [১৫. প্রজেক্ট স্ট্রাকচার](#১৫-প্রজেক্ট-স্ট্রাকচার)
- [১৬. API রেফারেন্স](#১৬-api-রেফারেন্স)
- [১৭. ডেমো মোড](#১৭-ডেমো-মোড)
- [১৮. কম্পোজিট স্কোরিং সিস্টেম](#১৮-কম্পোজিট-স্কোরিং-সিস্টেম)
- [১৯. কন্ট্রিবিউশন](#১৯-কন্ট্রিবিউশন)
- [২০. লাইসেন্স ও ডিসক্লেইমার](#২০-লাইসেন্স-ও-ডিসক্লেইমার)

---

## ১. অর্ডারফ্লো অ্যানালাইসিস কী? (একদম শুরু থেকে)

চলুন একদম সহজ ভাষায় বুঝি।

### 🟢 সাধারণ টেকনিক্যাল অ্যানালাইসিস vs অর্ডারফ্লো অ্যানালাইসিস

আপনি যখন সাধারণত চার্ট দেখেন (যেমন TradingView-এ), তখন আপনি দেখেন **ক্যান্ডেলস্টিক** — অর্থাৎ একটি নির্দিষ্ট সময়ে (যেমন ১ মিনিট, ৫ মিনিট, ১ ঘণ্টা) দাম কতে উঠেছিল, কতে নেমেছিল, কোথায় শুরু হয়েছিল, কোথায় শেষ হয়েছিল। এটাকে বলে **OHLC** (Open, High, Low, Close)। কিন্তু এতে একটা সমস্যা আছে — এটি শুধু বলে "কী হয়েছিল", কিন্তু বলে না "কে করেছিল" বা "কেন করেছিল"।

অর্ডারফ্লো অ্যানালাইসিস এর চেয়ে অনেক গভীরে যায়। এটি প্রতিটি **tick** (মার্কেটে যখন একটি লেনদেন হয়) আলাদাভাবে দেখে। প্রতিটি tick-এ তিনটি তথ্য থাকে:
- **দাম (price)** — কত দামে লেনদেন হলো
- **পরিমাণ (volume/size)** — কতগুলো কন্ট্রাক্ট/শেয়ার লেনদেন হলো
- **পক্ষ (side)** — ক্রেতা (buyer) নাকি বিক্রেতা (seller) এগিয়ে এসেছিল

```
সাধারণ টেকনিক্যাল অ্যানালাইসিস          অর্ডারফ্লো অ্যানালাইসিস
─────────────────────────────             ─────────────────────────────
যা দেখে: OHLC ক্যান্ডেল                    যা দেখে: প্রতিটি tick (দাম + ভলিউম + পক্ষ)
টাইমফ্রেম: 1m, 5m, 1H                     টাইমফ্রেম: Tick-লেভেল (মিলিসেকেন্ড)
প্রশ্নের উত্তর: কী হয়েছিল?                  প্রশ্নের উত্তর: কে করেছিল এবং কেন?
ইন্ডিকেটর: RSI, MACD, MA                  ইঞ্জিন: Delta, Footprint, Volume Profile, Orderbook
পিছিয়ে আছে: হ্যাঁ (গড় নেয়)                রিয়েল-টাইম: হ্যাঁ (এখনকার অবস্থা দেখায়)
```

### 🔑 মূল ধারণাগুলো (Key Concepts) — বিগিনারদের জন্য সহজ ব্যাখ্যা

নিচের টেবিলে সবচেয়ে গুরুত্বপূর্ণ কিছু ধারণা সহজ বাংলায় বুঝিয়ে দেওয়া হলো:

| ধারণা (Concept) | এটি কী মাপে | কেন দরকার |
|---------|-----------------|----------------|
| **Delta** | প্রতিটি ক্যান্ডেলে ক্রেতাদের ভলিউম বিয়োগ বিক্রেতাদের ভলিউম | কে বেশি আগ্রাসী — ক্রেতা না বিক্রেতা, তা বোঝায় |
| **Cumulative Delta** | Delta-র ক্রমিক যোগফল (সময়ের সাথে) | ক্রয়/বিক্রয় চাপ বাড়ছে নাকি কমছে, তা বোঝায় |
| **Footprint** | ক্যান্ডেলের ভেতরে প্রতিটি দামে কতটা bid/ask হয়েছে | ক্যান্ডেলের ভেতরে ভারী ট্রেড কোথায় হয়েছিল |
| **Volume Profile** | একটি সেশনে প্রতিটি দামে মোট কত ভলিউম ট্রেড হয়েছে | "Fair value" কোথায় — POC, VAH, VAL |
| **Orderbook** | প্রতিটি দামে কতগুলো লিমিট অর্ডার অপেক্ষা করছে | "দেয়াল" কোথায়? পাতলা লেভেল = সহজে ভাঙা যায় |
| **Absorption** | অনেক আগ্রাসী ভলিউম কিন্তু দাম নড়ল না | কেউ লিমিট অর্ডার দিয়ে একটি লেভেল রক্ষা করছে |
| **Initiative** | আগ্রাসী ভলিউম এবং দামও সেই অনুযায়ী নড়ছে | বড় প্রতিষ্ঠান দৃঢ়তার সাথে দাম ঠেলে দিচ্ছে |

### 💡 একটি বাস্তব উদাহরণ দিয়ে বুঝি

ধরুন, NAS100 (Nasdaq ইনডেক্স) একটি গুরুত্বপূর্ণ দামে এসে পৌঁছেছে — যেমন ১৭,৮২০। সাধারণ চার্টে আপনি শুধু দেখবেন দাম এখানে এসে উঠে গেছে। কিন্তু অর্ডারফ্লো দিয়ে আপনি দেখতে পাবেন:

- **১৭,৮২০-তে ৫০০টি ক্রেতার ট্রেড হলো**, কিন্তু দাম ১৭,৮২১-এ উঠতে পারল না
- মানে **বিক্রেতারা তাদের লিমিট অর্ডার দিয়ে ১৭,৮২০ ধরে রেখেছে** (একে বলে Absorption)
- এরপর যখন বিক্রেতারা শেষ হয়ে গেল, দাম হঠাৎ উপরে গেল — কারণ বাধা আর নেই

এই ধরনের জিনিস সাধারণ চার্ট দিয়ে কখনো দেখা যায় না। অর্ডারফ্লো দিয়ে দেখা যায়। আর এই প্রজেক্টটি ঠিক সেই কাজটাই করে — স্বয়ংক্রিয়ভাবে।

---

## ২. সিস্টেমের সংক্ষিপ্ত পরিচিতি

এই সিস্টেমটি কী কী করে? সংক্ষেপে:

- ✅ **রিয়েল-টাইমে মার্কেট ডেটা সংগ্রহ করে** — MetaTrader 5 (MT5) অথবা Bybit থেকে
- ✅ **প্রতিটি tick বিশ্লেষণ করে** — ক্রেতা বিক্রেতার চাপ বোঝার জন্য
- ✅ **৫টি প্যাটার্ন স্বয়ংক্রিয়ভাবে চিহ্নিত করে** — Absorption, Initiative, Sweep, Exhaustion, Divergence
- ✅ **দৈনিক দিক (Daily Bias) নির্ধারণ করে** — Volume Profile Shape অনুযায়ী (LONG / SHORT / NEUTRAL)
- ✅ **ট্রেড সিগন্যাল দেয়** — কখন entry নিতে হবে, কখন break-even করতে হবে, কখন exit করতে হবে
- ✅ **টেলিগ্রামে notification পাঠায়** — যাতে আপনি সবসময় আপডেট পান
- ✅ **ওয়েব ড্যাশবোর্ড দেয়** — যেখানে সব চার্ট, অর্ডারবুক, সিগন্যাল দেখা যায়
- ✅ **২৯টি ইনস্ট্রুমেন্ট একসাথে মনিটর করে** — NAS100, Gold, EURUSD, BTC ইত্যাদি

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OrderFlow Analysis Pro                              │
│                                                                             │
│  ┌──────────────────────┐     ┌──────────────────────────────────────┐      │
│  │   DATA SOURCES       │     │   ANALYTICS ENGINES (প্রতিটি ইনস্ট্রুমেন্টের জন্য) │
│  │                      │     │                                      │      │
│  │  ┌────────┐ ┌──────┐ │     │  Volume Profile  ── POC, VAH, VAL    │      │
│  │  │  MT5   │ │Bybit │ │────▶│  Delta Engine    ── vertical, horiz  │      │
│  │  │  Feed  │ │ Feed │ │     │  Footprint       ── bid/ask/level    │      │
│  │  └────────┘ └──────┘ │     │  Orderbook       ── L2 depth, thin   │      │
│  └──────────────────────┘     └───────────────┬──────────────────────┘      │
│                                               │                              │
│  ┌────────────────────────────────────────────▼──────────────────────────┐  │
│  │                    ৫টি প্যাটার্ন ডিটেক্টর                                 │  │
│  │  Absorption · Initiative · Sweep · Exhaustion · Divergence             │  │
│  └────────────────────────────────────────────┬──────────────────────────┘  │
│                                               │                              │
│  ┌────────────────────────────────────────────▼──────────────────────────┐  │
│  │                    সিগন্যাল প্রসেসিং                                    │  │
│  │  Profile Framing (P/b/D আকার) → Qualified Levels → Daily Bias         │  │
│  │  Signal Aggregator (state machine) → Composite Score (0-100)          │  │
│  └────────────┬──────────────────────────┬───────────────────────┘  │
│               │                          │                          │
│  ┌────────────▼──────────┐  ┌───────────▼────────────────────┐     │
│  │   টেলিগ্রাম অ্যালার্ট  │  │   FastAPI ড্যাশবোর্ড           │     │
│  │   Entry/BE/Trail/Exit │  │   16টি REST endpoints + WebSocket │  │
│  │   Daily Bias আপডেট    │  │   Charts, VP, Footprint, Orderbook│  │
│  └───────────────────────┘  │   Scanner, Strategy Status, Tape  │  │
│                              └───────────────────────────────────────┘     │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │   SQLite ডেটাবেস (WAL মোড)                                          │     │
│  │   ticks · candles · volume_profiles · signals · trade_journal     │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## ৩. সিস্টেমের আর্কিটেকচার (কীভাবে কাজ করে)

এই সিস্টেমটি একটি **পাইপলাইন** হিসেবে কাজ করে। চলুন ধাপে ধাপে বুঝি কীভাবে ডেটা এক জায়গা থেকে অন্য জায়গায় যায়।

### 📊 ডেটা ফ্লো পাইপলাইন

```
                     ┌─────────────┐
                     │  MT5 Feed   │──── Tick polling (প্রতি 100ms)
                     │  (495L)     │──── Market Book (DOM)
                     │             │──── Historical download (৩ দিন)
                     └──────┬──────┘
                            │
     ┌──────────────┐       │       ┌──────────────┐
     │  Bybit Feed  │───────┤       │   Database   │
     │  (209L)      │       ├──────▶│  (278L)      │
     │  WebSocket   │       │       │  SQLite WAL  │
     │  ফ্রি, কোনো key লাগে না│       │              │
     └──────────────┘       │       └──────────────┘
                            ▼
                   ┌─────────────────┐
                   │ Candle Builder  │ ← Tick থেকে 1m ক্যান্ডেল বানায়
                   │ (133L)          │ ← প্রতিটি লেভেলে footprint
                   └────────┬────────┘
                            │
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
     ┌──────────────┐ ┌──────────┐ ┌──────────────┐
     │ Volume Prof. │ │  Delta   │ │  Footprint   │
     │ Engine (258L)│ │Engine    │ │  Engine      │
     │              │ │ (197L)   │ │ (181L)       │
     │ POC/VAH/VAL  │ │ Vert/Hor│ │ Bid/Ask/Lvl  │
     │ LVN/Shape    │ │ Cumul.   │ │ Imbalance    │
     └──────┬───────┘ └────┬─────┘ └──────┬───────┘
            │              │              │
            ▼              ▼              ▼
     ┌─────────────────────────────────────────┐
     │        ORDERBOOK TRACKER (208L)          │
     │  L2 depth · Thin levels · Consumptions   │
     │  Path of least resistance                │
     └──────────────────┬──────────────────────┘
                        │
        ┌───────┬───────┼───────┬───────┬───────┐
        ▼       ▼       ▼       ▼       ▼       │
   ┌────────┐┌────────┐┌──────┐┌────────┐┌────────┐
   │Absorp- ││Initia- ││Sweep ││Exhaus- ││Diverg- │
   │tion    ││tive    ││      ││tion    ││ence    │
   │(257L)  ││(133L)  ││(142L)││(228L)  ││(159L)  │
   └───┬────┘└───┬────┘└──┬───┘└───┬────┘└───┬────┘
       │         │        │        │         │
       └─────────┴────┬───┴────────┴─────────┘
                      ▼
            ┌─────────────────────┐
            │  Profile Framing    │ ← P/b/D আকার → Daily Bias
            │  (343L)             │ ← Qualified Levels (VAH/VAL/POC/LVN/Merged)
            └─────────┬───────────┘
                      ▼
            ┌─────────────────────┐
            │  Signal Aggregator  │ ← State machine (৬টি স্টেট)
            │  (516L)             │ ← Composite scoring (0-100)
            │                     │ ← SL/TP calculation
            └──────┬──────────────┘
                   │
       ┌───────────┼───────────────┐
       ▼           ▼               ▼
 ┌──────────┐ ┌──────────┐  ┌───────────────┐
 │ Telegram │ │Dashboard │  │  Database     │
 │ Bot      │ │ FastAPI  │  │  Journal      │
 │ (202L)   │ │ (1015L)  │  │  Logging      │
 └──────────┘ └──────────┘  └───────────────┘
```

### 🔍 পাইপলাইন ধাপে ধাপে ব্যাখ্যা

১. **ডেটা সংগ্রহ (Data Collection):** MT5 অথবা Bybit থেকে রিয়েল-টাইমে প্রতিটি tick (লেনদেন) সংগ্রহ করা হয়। প্রতিটি tick-এ থাকে দাম, পরিমাণ, এবং ক্রেতা/বিক্রেতার পক্ষ।

২. **ক্যান্ডেল তৈরি (Candle Building):** প্রতিটি tick থেকে ১ মিনিটের ক্যান্ডেল তৈরি করা হয়। প্রতিটি ক্যান্ডেলের ভেতরে দাম অনুযায়ী ভলিউম ভাগ করা হয় (Footprint)।

৩. **অ্যানালিটিক্স ইঞ্জিন চালানো:** চারটি আলাদা ইঞ্জিন একসাথে কাজ করে —
   - **Volume Profile Engine:** কোথায় সবচেয়ে বেশি ট্রেড হয়েছে (POC), value area কোথায় (VAH, VAL)
   - **Delta Engine:** প্রতিটি ক্যান্ডেলে ক্রেতা বেশি না বিক্রেতা
   - **Footprint Engine:** ক্যান্ডেলের ভেতরে প্রতিটি দামে কত bid কত ask হয়েছে
   - **Orderbook Tracker:** অর্ডারবুকে কোথায় "পাতলা" লেভেল আছে যা সহজে ভাঙা যাবে

৪. **প্যাটার্ন ডিটেকশন:** ৫টি আলাদা ডিটেক্টর এই অ্যানালিটিক্স ডেটা দেখে সিদ্ধান্ত নেয় — কোনো প্যাটার্ন তৈরি হচ্ছে কিনা।

৫. **সিগন্যাল অ্যাগ্রিগেশন:** সব প্যাটার্ন ডিটেক্টরের আউটপুট একত্রিত করে একটি **composite score (0-100)** তৈরি করা হয়। যদি score যথেষ্ট বেশি হয়, তবে ট্রেড সিগন্যাল তৈরি হয়।

৬. **নোটিফিকেশন:** সিগন্যাল টেলিগ্রামে পাঠানো হয়, ড্যাশবোর্ডে দেখানো হয়, এবং ডেটাবেসে সংরক্ষণ করা হয়।

### 🧩 মডিউল ডিপেন্ডেন্সি গ্রাফ

```
main.py (666L) ─── সিস্টেম অর্কেস্ট্রেটর (সব একসাথে চালায়)
    │
    ├── config/settings.py (946L) ─── ২৯টি ইনস্ট্রুমেন্ট কনফিগ, ১০টি কনফিগ ডেটাক্লাস
    │
    ├── data/
    │   ├── models.py (290L) ─── ৭টি ডেটাক্লাস: Tick, Candle, Signal, TradeState...
    │   ├── candle_builder.py (133L) ─── Tick থেকে 1m অ্যাগ্রিগেশন + footprint
    │   ├── mt5_feed.py (495L) ─── MT5 টার্মিনাল: ticks, book, history
    │   ├── bybit_feed.py (209L) ─── Bybit WebSocket: trades + orderbook
    │   └── database.py (278L) ─── SQLite: ৫টি টেবিল, WAL মোড
    │
    ├── analytics/
    │   ├── volume_profile.py (258L) ─── POC/VAH/VAL/LVN/shape
    │   ├── delta.py (197L) ─── Vertical + horizontal + cumulative delta
    │   ├── footprint.py (181L) ─── Bid/ask প্রতি লেভেলে, imbalance ডিটেকশন
    │   └── orderbook.py (208L) ─── L2 depth, thin levels, consumption tracking
    │
    ├── patterns/
    │   ├── absorption.py (257L) ─── Effort >> result ডিটেকশন
    │   ├── initiative.py (133L) ─── Effort = result (momentum)
    │   ├── sweep.py (142L) ─── Thin book displacement
    │   ├── exhaustion.py (228L) ─── Extreme-এ volume কমছে
    │   └── divergence.py (159L) ─── Price vs delta disagreement
    │
    ├── signals/
    │   ├── profile_framing.py (343L) ─── Daily bias + qualified levels
    │   └── aggregator.py (516L) ─── State machine + composite scoring
    │
    ├── alerts/
    │   └── telegram_bot.py (202L) ─── Telegram notifications
    │
    └── dashboard/
        ├── app.py (1015L) ─── FastAPI REST + WebSocket server
        ├── websocket_manager.py (186L) ─── ৯টি চ্যানেল ব্রডকাস্ট
        ├── demo_data.py (782L) ─── Deterministic demo data generator
        ├── __main__.py (35L) ─── Standalone launcher
        └── static/ ─── HTML/JS/CSS frontend (৮টি ফাইল, ৪,৪২০ লাইন)
```

---

## ৪. ৫টি মূল প্যাটার্ন ডিটেক্টর

এই সিস্টেমটি Fabio Testa-র মেথডলজি অনুযায়ী **৫টি মাইক্রোস্ট্রাকচার প্যাটার্ন** চিহ্নিত করে। প্রতিটি প্যাটার্ন একটি **strength score (0-100)** এবং একটি **দিক (BUY/SELL)** আউটপুট দেয়।

### 🎯 প্যাটার্ন ওভারভিউ

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ৫টি প্যাটার্ন ডিটেক্টর                            │
│                                                                     │
│  ১. ABSORPTION       ২. INITIATIVE      ৩. SWEEP                    │
│  Effort >> Result    Effort = Result    Thin Book Displacement      │
│  ██████████          ██████████         ██████                      │
│  ██████████  (দাম    ██████████  (দাম   ██░░░░░░░ (দাম দ্রুত         │
│  ██████████   নডে না) ██████████   নডে) ░░░░░░░░   নডে)             │
│  ক্রেতা/বিক্রেতা       দিক নির্দেশক       কম ভলিউমে                   │
│  লেভেল রক্ষা করছে    conviction         খালি লেভেল পার হচ্ছে         │
│                                                                     │
│  ৪. EXHAUSTION       ৫. DIVERGENCE                                 │
│  Effort কমছে         Price vs Delta disagreement                   │
│  ██  █  █            Price: ↗↗↗ NEW HIGH                            │
│  █  █  ▓             Delta: ↗↗↘  (failing)                         │
│  █  ▓  ░             Trend reversal warning                        │
│  ▓  ░  ░                                                           │
│  Extreme-এ                                                          │
│  volume কমছে                                                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 📋 ডিটেকশন বিস্তারিত

| # | প্যাটার্ন | ডিটেকশন লজিক | সোর্স ডেটা | সিগন্যালের উদ্দেশ্য |
|---|---------|----------------|-------------|----------------|
| ১ | **Absorption** | ২টি পদ্ধতি: (ক) Delta/price mismatch — positive delta + red candle = বিক্রেতারা absorb করছে, (খ) একটি লেভেলে বেশি ভলিউম + কম displacement + বারবার attempt | Delta, Footprint, Price | VAH/VAL-এ **entry signal** |
| ২ | **Initiative** | ৫টি ক্রাইটেরিয়া: delta ≥ threshold, volume ≥ 1.5x average, body ≥ 3 ticks, delta/price aligned, one-sided imbalance bonus | Delta, Footprint, Volume | **Break-even / trail trigger** |
| ৩ | **Sweep** | দাম ≥৩টি thin orderbook level পার হচ্ছে + প্রতি লেভেলে কম ভলিউম + thin book confirmation (swept side-এ ≥২টি thin level) | Orderbook, Price | **Liquidity grab / reversal alert** |
| ৪ | **Exhaustion** | দাম trend করছে + volume >৩০% কমছে + negative volume/delta trend + optional contrarian imbalance at extreme | Volume trend, Delta ROC, Footprint | **Exit warning** — momentum fading |
| ৫ | **Divergence** | দাম new high/low করল কিন্তু cumulative delta peak/trough confirm করল না (<৮০% of prior) | Price, Cumulative Delta peaks | **Trend reversal warning** |

### 🧮 স্ট্রেংথ স্কোর ক্যালকুলেশন

| প্যাটার্ন | স্কোর ফর্মুলা | রেঞ্জ |
|---------|--------------|-------|
| Absorption | `(volume / min_aggressive) * 40` অথবা `(vol / min_aggressive) * 30 + attempts * 15` | 0-75 |
| Initiative | `(delta/threshold)*20 + vol_accel*15 + body_ticks*5 + imbalance_count*10` | 0-50+ |
| Sweep | `levels*15 + efficiency*20 + displacement*1000 + thin_confirm*15` | 30-100 |
| Exhaustion | `40 + |vol_trend|*5 + |delta_roc|*5 + contrarian_bonus(20)` | 40-70 |
| Divergence | `30 + (1 - ratio)*40 + price_new_extreme*10` | 30-80 |

### 💡 প্যাটার্নগুলো সহজ ভাষায় বুঝি

**১. Absorption (শোষণ):**
ধরুন অনেক ক্রেতা আগ্রাসীভাবে কিনছে, কিন্তু দাম উপরে যাচ্ছে না। এর মানে হলো কেউ বড় বড় লিমিট সেল অর্ডার দিয়ে দাম ধরে রেখেছে। যখন সেই বিক্রেতা শেষ হয়ে যাবে, দাম হঠাৎ উপরে যাবে। এটি একটি BUY সিগন্যাল।

**২. Initiative (উদ্যোগ):**
বড় প্রতিষ্ঠান যখন দৃঢ়তার সাথে কোনো দিকে ট্রেড করে — দামও সেই দিকে যায়, ভলিউমও বাড়ে। এটি momentum-এর লক্ষণ। এটি ট্রেড চালু থাকলে break-even ট্রিগার হয়।

**৩. Sweep (সুইপ):**
অর্ডারবুকে কিছু জায়গায় খুব কম অর্ডার থাকে (thin level)। দাম যখন সহজেই এই পাতলা লেভেলগুলো পার হয়ে যায়, তখন বোঝা যায় যে বড় ক্রেতা/বিক্রেতা অপেক্ষা করছে না — তারা মার্কেট অর্ডার দিয়ে লিকুইডিটি ধরে নিচ্ছে। এটি প্রায়ই reversal-এর আগে ঘটে।

**৪. Exhaustion (ক্লান্তি):**
যখন কোনো trend-এ ভলিউম কমতে থাকে, তখন বোঝা যায় trend-এর শক্তি ফুরিয়ে এসেছে। এটি exit করার সংকেত।

**৫. Divergence (বৈপরীত্য):**
দাম new high করছে কিন্তু delta (ক্রেতার চাপ) আগের high-এর চেয়ে কম। মানে দাম বাড়ছে ঠিকই, কিন্তু ক্রেতার শক্তি কমছে। এটি reversal-এর পূর্বাভাস।

---

## ৫. ভলিউম প্রোফাইল ফ্রেমিং (দৈনিক দিক নির্ধারণ)

Fabio Testa-র **profile shape analysis** দিয়ে সিস্টেমটি দৈনিক দিক (LONG / SHORT / NEUTRAL) নির্ধারণ করে এবং কোন কোন লেভেল থেকে ট্রেড করা উচিত (qualified levels) তা চিহ্নিত করে।

### 📐 প্রোফাইল আকার (Profile Shapes)

```
P-SHAPE (ক্রেতার নিয়ন্ত্রণ)        b-SHAPE (বিক্রেতার নিয়ন্ত্রণ)
Volume │                           Volume │
  █    │                                  │ █
  ██   │                                  │ ██
  ███  │     POC > 65%                    │ ███     POC < 35%
  ████ │     Bias: LONG                   │ ████    Bias: SHORT
  █████│                                  │ ██████
───────┼────────── Price            ──────┼────────── Price
  VAL  │  POC  VAH                         VAH  POC  VAL

D-SHAPE (ব্যালেন্সড)                  DOUBLE DISTRIBUTION
Volume │                           Volume │
  █    │       █                          │ ████    ████
  ██   │      ██                          │ ████    ████
  ███  │     ███   POC ~50%               │  ░░░░░░░░░░   (valley)
  ████ │    ████  Bias: NEUTRAL           │ ████    ████  Bias: TRANSITION
───────┼────────── Price            ──────┼────────────────── Price
  VAL  │ POC │ VAH                         VAH₁  VAL₁  VAH₂  VAL₂
```

| আকার | POC পজিশন | Bias | Confidence Base | ট্রেডিং প্ল্যান |
|-------|-------------|------|----------------|-------------|
| **P-shape** | নিচ থেকে >65% | LONG | 40 + poc_pct×30 | ক্রেতার নিয়ন্ত্রণ, VAL-এ dip কিনুন |
| **b-shape** | নিচ থেকে <35% | SHORT | 40 + (1-poc_pct)×30 | বিক্রেতার নিয়ন্ত্রণ, VAH-এ rally বিক্রি করুন |
| **D-shape** | ~50% | NEUTRAL | 20 | ব্যালেন্সড, extreme থেকে fade করুন |
| **Double Distribution** | Bimodal (valley <50% of peaks) | NEUTRAL | 30 | Transition — breakout-এর জন্য দেখুন |

### 🎯 Qualified Levels (ট্রেড যোগ্য লেভেল)

```
┌─────────────────────────────────────────────────────────────────┐
│                  QUALIFIED LEVELS (এখান থেকে ট্রেড করুন)         │
│                                                                  │
│  Price ▲                                                         │
│       │     ┌─── VAH (Value Area High) ─── SELL ZONE            │
│       │     │                                                    │
│       │     │    ┌── MERGED VAH ─── Strong SELL (str=70)        │
│       │     │    │  (একাধিক দিন জুড়ে confluent)                  │
│       │     │                                                    │
│       │     │  ┌── LVN (Low Volume Node) ─── Rebalancing        │
│       │     │  │  (price magnet — gaps দ্রুত পূরণ হয়)            │
│       │     │  │                                                │
│       │  ┌──┤  │  ┌── POC (Point of Control) ─── Pivot          │
│       │  │  │  │  │  (সর্বোচ্চ ভলিউম = fair value)                │
│       │  │  │  │  │                                            │
│       │  │  ├──┤  │  ┌── MERGED VAL ─── Strong BUY (str=70)    │
│       │  │  │  │  │  │  (একাধিক দিন জুড়ে confluent)              │
│       │  │  │  │  │  │                                        │
│       │  └──┤  │  │  │  └── VAL (Value Area Low) ─── BUY ZONE  │
│       │     │  │  │                                           │
│       └─────┘  │  └────────────────────────────────────         │
│                │                                                 │
│  Confluence Bonus: একাধিক দিন লেভেল ম্যাচ করলে +20 strength      │
│  Multi-day merge: overlapping profiles (>30% VA overlap) merge  │
└─────────────────────────────────────────────────────────────────┘
```

### 📅 মাল্টি-ডে কন্টেক্সট চেক

| চেক | কী করে | প্রভাব |
|-------|-------------|--------|
| Value accepted higher | বর্তমান VA পূর্ববর্তী VA-র উপরে | bias-এর সাথে aligned হলে +15 confidence |
| VAH rejection | একাধিক দিন VAH-এ দাম reject হয়েছে | Bias → WARNING, composite score-এ -10 penalty |
| Failed auction ("hooks") | VAL-এর নিচে bullish hook, VAH-এর উপরে bearish hook | Confidence কমায় |

---

## ৬. স্টেট মেশিন ট্রেড লাইফসাইকেল

প্রতিটি ইনস্ট্রুমেন্টের জন্য একটি আলাদা **state machine** চলে। সিস্টেম qualified levels দেখে, absorption entry চিহ্নিত করে, break-even এবং trailing stop-এর মাধ্যমে ট্রেড পরিচালনা করে, এবং শক্তিশালী exit signal-এ স্বয়ংক্রিয়ভাবে ট্রেড বন্ধ করে।

```
╔══════════════════════════════════════════════════════════════════════════╗
║                    স্টেট মেশিন ট্রেড লাইফসাইকেল                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║   ┌─────────────────────────────────────────────────────────────┐        ║
║   │  NO ACTIVE TRADE (কোনো ট্রেড নেই)                            │        ║
║   │  দাম qualified level-এ পৌঁছাচ্ছে (strength >= 50)              │        ║
║   │  Aggregator স্বয়ংক্রিয়ভাবে level watch করে                   │        ║
║   └────────────────────────┬────────────────────────────────────┘        ║
║                            │                                             ║
║                            ▼                                             ║
║   ┌─────────────────────────────────────────────────────────────┐        ║
║   │  WATCHING (দেখছে)                                            │        ║
║   │  level-এ absorption বা sweep signal-এর জন্য মনিটরিং           │        ║
║   └───────┬────────────────────────────────┬────────────────────┘        ║
║           │ ABSORPTION পাওয়া গেল           │ SWEEP পাওয়া গেল              ║
║           │ (composite >= 40)              │ (thin book displacement)    ║
║           ▼                                 ▼                            ║
║   ┌──────────────┐               ┌──────────────────────┐               ║
║   │ ABSORPTION   │               │ ALERT ONLY           │               ║
║   │ DETECTED     │               │ (sweep notification, │               ║
║   │ (transient)  │               │  entry নেই)          │               ║
║   └──────┬───────┘               └──────────────────────┘               ║
║          │ Entry signal পাঠানো হলো, SL/TP ক্যালকুলেট হলো                ║
║          ▼                                                                ║
║   ┌─────────────────────────────────────────────────────────────┐        ║
║   │  POSITION_OPEN (ট্রেড চালু)                                  │        ║
║   │  ট্রেড নেওয়া হয়েছে। initiative (BE trigger) এর জন্য অপেক্ষা    │        ║
║   │  অথবা exit warning (exhaustion/divergence) এর জন্য দেখছে     │        ║
║   └───────┬────────────────────────────────┬────────────────────┘        ║
║           │ INITIATIVE (একই দিকে)         │ EXIT WARNING (বিপরীত দিকে)  ║
║           │ SL কে entry price-এ নিয়ে যান   │ str >= 70 → স্বয়ংক্রিয় বন্ধ ║
║           ▼                                 ▼                            ║
║   ┌──────────────┐               ┌──────────────────────┐               ║
║   │ BREAK_EVEN   │               │ CLOSED               │               ║
║   │ SL = entry   │               │ (শক্ত exit signal-এ   │               ║
║   │ Risk-free    │               │  স্বয়ংক্রিয় বন্ধ)      │               ║
║   └──────┬───────┘               └──────────────────────┘               ║
║          │ INITIATIVE (একই দিকে)                                             ║
║          │ SL কে candle extreme-এ ট্রেইল করুন                                ║
║          ▼                                                                  ║
║   ┌─────────────────────────────────────────────────────────────┐         ║
║   │  TRAILING (ট্রেইল করছে)                                     │         ║
║   │  SL কে candle low (longs) বা high (shorts)-এ ট্রেইল করে      │         ║
║   │  প্রতিটি নতুন initiative print ট্রেইল সরায়                     │         ║
║   └───────┬────────────────────────────────┬────────────────────┘         ║
║           │ আরো INITIATIVE                │ EXIT WARNING (str>=70)        ║
║           │ ট্রেইল চালিয়ে যান              │ অথবা SL hit                   ║
║           ▼                                 ▼                              ║
║   ┌──────────────┐               ┌──────────────────────┐                ║
║   │ (loop back)  │               │ CLOSED               │                ║
║   │ TRAILING     │──────────────▶│ Trade journal +      │                ║
║   │              │               │ Telegram-এ log হলো   │                ║
║   └──────────────┘               └──────────────────────┘                ║
║                                                                            ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### 🔄 স্টেটগুলো সহজ ভাষায়

১. **NO ACTIVE TRADE:** কোনো ট্রেড নেই। সিস্টেম দেখছে দাম কোনো গুরুত্বপূর্ণ লেভেলে কাছাকাছি আসে কিনা।
২. **WATCHING:** কোনো লেভেলে দাম পৌঁছেছে, সিস্টেম absorption বা sweep-এর জন্য দেখছে।
৩. **ABSORPTION DETECTED:** Absorption পাওয়া গেছে — entry signal পাঠানো হলো, SL/TP ক্যালকুলেট হলো।
৪. **POSITION_OPEN:** ট্রেড নেওয়া হয়েছে। এখন দুটি জিনিসের জন্য অপেক্ষা — initiative (একই দিকে চললে break-even করবে) বা exit warning (বিপরীত দিকে গেলে বন্ধ করবে)।
৫. **BREAK_EVEN:** Stop-loss কে entry price-এ নিয়ে যাওয়া হয়েছে — এখন ট্রেড রিস্ক-ফ্রি।
৬. **TRAILING:** Stop-loss কে প্রতিটি নতুন initiative candle-এর extreme-এ ট্রেইল করা হচ্ছে।
৭. **CLOSED:** ট্রেড বন্ধ — SL hit হয়েছে বা স্বয়ংক্রিয়ভাবে বন্ধ হয়েছে। Trade journal-এ লগ হয়েছে।

---

## ৭. সাপোর্টেড ইনস্ট্রুমেন্ট (২৯টি)

প্রতিটি ইনস্ট্রুমেন্টের জন্য **আগে থেকে tune করা thresholds** আছে — সব ৫টি প্যাটার্ন ডিটেক্টরের জন্য, প্রতিটির volatility এবং tick size অনুযায়ী।

### 📈 ইনডেক্স ফিউচার্স (৯টি)

| ইনস্ট্রুমেন্ট | Tick Size | Absorption Min Vol | Initiative Min Delta | VP Tick Size | সেশন |
|-----------|-----------|-------------------|---------------------|-------------|---------|
| NAS100 | 0.1 | 50 | 30 | 1.0 | NY Cash |
| SP500 | 0.1 | 40 | 25 | 1.0 | NY Cash |
| DJ30 | 1.0 | 40 | 25 | 5.0 | NY Cash |
| UK100 | 0.1 | 30 | 20 | 1.0 | London |
| DAX40 | 0.1 | 30 | 20 | 2.0 | London |
| NIKKEI225 | 1.0 | 30 | 20 | 50.0 | Asian |
| CAC40 | 0.1 | 25 | 18 | 1.0 | London |
| ASX200 | 0.1 | 25 | 18 | 1.0 | Asian |
| HK50 | 1.0 | 25 | 18 | 5.0 | Asian |

### 🥇 মেটাল, এনার্জি, ক্রিপ্টো

| ইনস্ট্রুমেন্ট | ক্যাটাগরি | Tick Size | VP Tick Size | সেশন |
|-----------|----------|-----------|-------------|---------|
| XAUUSDT (স্বর্ণ) | Metal | 0.01 | 0.50 | NY Cash |
| XAGUSD (রূপা) | Metal | 0.001 | 0.05 | Full Day |
| USOIL | Energy | 0.01 | 0.10 | NY Cash |
| UKOIL | Energy | 0.01 | 0.10 | London |
| BTCUSDT | Crypto | 0.01 | 10.0 | Full Day |

### 💱 ফরেক্স (১০টি পেয়ার)

| ইনস্ট্রুমেন্ট | Tick Size | VP Tick Size | সেশন |
|-----------|-----------|-------------|---------|
| EURUSD | 0.00001 | 0.0005 | Full Day |
| GBPUSD | 0.00001 | 0.0005 | Full Day |
| USDJPY | 0.001 | 0.05 | Full Day |
| AUDUSD | 0.00001 | 0.0005 | Full Day |
| USDCAD | 0.00001 | 0.0005 | Full Day |
| USDCHF | 0.00001 | 0.0005 | Full Day |
| NZDUSD | 0.00001 | 0.0005 | Full Day |
| EURGBP | 0.00001 | 0.0005 | Full Day |
| EURJPY | 0.001 | 0.05 | Full Day |
| GBPJPY | 0.001 | 0.05 | Full Day |

### 🏢 মার্কিন স্টক (৭টি)

| ইনস্ট্রুমেন্ট | Tick Size | VP Tick Size | সেশন |
|-----------|-----------|-------------|---------|
| AAPL | 0.01 | 0.50 | NY Cash |
| TSLA | 0.01 | 0.50 | NY Cash |
| AMZN | 0.01 | 0.50 | NY Cash |
| MSFT | 0.01 | 0.50 | NY Cash |
| NVDA | 0.01 | 0.50 | NY Cash |
| META | 0.01 | 0.50 | NY Cash |
| GOOGL | 0.01 | 0.50 | NY Cash |

---

## ৮. ডেটা সোর্স (MT5 + Bybit)

### 🔌 ডুয়াল ফিড আর্কিটেকচার

সিস্টেমটি দুটি আলাদা ডেটা সোর্স থেকে ডেটা নিতে পারে — একসাথে বা আলাদাভাবে।

```
┌────────────────────────────────────────────────────────────┐
│                     ডেটা সোর্স অপশন                          │
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────────┐   │
│  │      MT5 FEED       │    │      BYBIT FEED         │   │
│  │                      │    │                         │   │
│  │  সোর্স: MT5 টার্মিনাল │    │  সোর্স: Bybit WebSocket │   │
│  │  দরকার: অ্যাকাউন্ট    │    │  দরকার: কিছুই না          │   │
│  │  Ticks: 100ms polling│    │  Ticks: রিয়েল-টাইম স্ট্রিম │   │
│  │  Orderbook: DOM data │    │  Orderbook: ৫০ লেভেল    │   │
│  │  History: ৩ দিন পর্যন্ত│    │  History: নেই            │   │
│  │  Aggressor: Buy/Sell │    │  Aggressor: Trade side  │   │
│  │  flag from MT5       │    │  from Bybit API         │   │
│  └──────────┬───────────┘    └───────────┬─────────────┘   │
│             │                             │                  │
│             │  DATA_SOURCE = "MT5"        │  "BYBIT"         │
│             │  DATA_SOURCE = "BOTH" ──────┘                  │
│             │                                                │
│             ▼                                                │
│  ┌─────────────────────────────────────┐                    │
│  │  Symbol Auto-Discovery (MT5)        │                    │
│  │  ২০০+ broker-specific name variants │                    │
│  │  যেমন USTEC, USTECm, NAS100, US100 │                    │
│  └─────────────────────────────────────┘                    │
└────────────────────────────────────────────────────────────┘
```

### 🆚 কোনটি ব্যবহার করবেন?

**Bybit (নতুনদের জন্য সুপারিশকৃত):**
- ✅ সম্পূর্ণ ফ্রি
- ✅ কোনো অ্যাকাউন্ট বা key লাগে না
- ✅ রিয়েল-টাইম ডেটা
- ❌ Historical ডেটা নেই (সেশন শুরু থেকে শুধু)
- ❌ শুধু crypto-তে কাজ করে

**MT5 (ইনডেক্স/ফরেক্স/স্টকের জন্য):**
- ✅ NAS100, XAUUSD, EURUSD ইত্যাদির জন্য প্রয়োজন
- ✅ ৩ দিনের historical ডেটা (warmup-এর জন্য)
- ✅ Orderbook DOM ডেটা
- ❌ MetaTrader 5 টার্মিনাল ও অ্যাকাউন্ট দরকার

**BOTH (সবচেয়ে ভালো):** দুটি ফিড একসাথে চালায় — একটির সমস্যা হলে অন্যটি fallback হিসেবে কাজ করে।

### 🔄 MT5 Symbol ম্যাপিং

সিস্টেমটি ২০০+ broker-specific naming variants স্বয়ংক্রিয়ভাবে detect করে:

| অভ্যন্তরীণ | MT5 Symbol | বিকল্প |
|----------|-----------|-------------|
| NAS100 | USTECm | USTEC, NAS100, US100, NQ100, NAS100USD... |
| XAUUSDT | XAUUSDm | XAUUSD, GOLD... |
| EURUSD | EURUSDm | EURUSD, EUR/USD... |
| BTCUSDT | BTCUSDm | BTCUSD, BTC/USD... |

---

## ৯. ড্যাশবোর্ড

একটি সুন্দর ওয়েব ড্যাশবোর্ড যেখানে সব কিছু ভিজুয়ালি দেখা যায়।

### 🖥️ ফ্রন্টএন্ড কম্পোনেন্ট (৮টি কাস্টম JS মডিউল)

```
┌──────────────────────────────────────────────────────────────────────┐
│                     অর্ডারফ্লো ড্যাশবোর্ড                              │
│                                                                      │
│  ┌───────────────────────────────────┐  ┌────────────────────────┐  │
│  │        PRICE CHART (app.js)       │  │   VOLUME PROFILE       │  │
│  │   TradingView lightweight-charts  │  │   Horizontal bars      │  │
│  │   Signal markers overlay:         │  │   POC, VAH, VAL marks  │  │
│  │   ▲ Absorption (teal)            │  │   Shape classification │  │
│  │   ▲ Initiative (green)           │  │   LVN markers          │  │
│  │   ▲ Sweep (purple)               │  └────────────────────────┘  │
│  │   ● Exhaustion (yellow)                                        │
│  │   ● Divergence (orange)          ┌────────────────────────┐    │
│  │   ● Entry/Exit markers           │   FOOTPRINT CHART      │    │
│  └───────────────────────────────────┘│   Bid/Ask per level   │    │
│                                       │   Imbalance highlights│    │
│  ┌───────────────────────────────────┐└────────────────────────┘  │
│  │  SIGNAL CARDS (signals.js)        │                             │
│  │   রিয়েল-টাইম ট্রেড সুপারিশ         │  ┌────────────────────────┐│
│  │   Entry/SL/TP/RR display          │  │  ORDERBOOK DEPTH       ││
│  │   Pattern breakdown               │  │  Bid/Ask ladder        ││
│  │   Grade (A+/A/B/C)                │  │  Thin level markers    ││
│  └───────────────────────────────────┘  │  Spread indicator      ││
│                                         └────────────────────────┘│
│  ┌───────────────────────────────────┐  ┌────────────────────────┐│
│  │  PERFORMANCE (performance.js)     │  │  TIME & SALES (tape.js)││
│  │  Win rate, PnL, RR distribution   │  │  Tick-by-tick feed     ││
│  │  Trade history                    │  │  Big trade highlights  ││
│  └───────────────────────────────────┘  └────────────────────────┘│
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              MICROSTRUCTURE (microstructure.js)               │  │
│  │  Market state · Session · Absorption · Delta · Exhaustion     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 📡 WebSocket চ্যানেল (৯টি)

ড্যাশবোর্ড সার্ভারের সাথে WebSocket দিয়ে সংযুক্ত থাকে। ৯টি আলাদা চ্যানেলে ডেটা আসে:

| চ্যানেল | ডেটা | Throttle | প্রায়োরিটি |
|---------|------|----------|----------|
| `tick` | দাম, পরিমাণ, পক্ষ | 200ms | High |
| `candle` | OHLCV + delta | None (immediate) | Critical |
| `signal` | AggregatedSignal | None (immediate) | Critical |
| `trade_state` | TradePhase transitions | None (immediate) | Critical |
| `volume_profile` | POC/VAH/VAL/shape | None | Normal |
| `bias` | DailyBias updates | None | Normal |
| `orderbook` | L2 depth + imbalance | 500ms | Normal |
| `delta` | Cumulative delta history | 200ms | Normal |
| `stats` | সিস্টেম-wide per-instrument | 5000ms | Low |

---

## ১০. টেলিগ্রাম অ্যালার্ট

প্রতিটি ট্রেড lifecycle event-এর জন্য স্বয়ংক্রিয় notification:

| অ্যালার্ট টাইপ | Trigger | কনটেন্ট |
|-----------|---------|---------|
| **ENTRY SIGNAL** | Qualified level-এ absorption, composite ≥40 | দিক, score, প্যাটার্ন, delta, ভলিউম, bias, entry/SL/TP/RR |
| **BREAK EVEN** | Entry-র পর প্রথম initiative auction | SL কে entry price-এ নেওয়া হলো — risk-free ট্রেড |
| **TRAIL UPDATE** | পরবর্তী initiative prints | নতুন SL level, ট্রেইল progress |
| **EXIT SIGNAL** | ট্রেড বন্ধ (SL hit বা স্বয়ংক্রিয়) | PnL ticks, RR achieved, trade summary |
| **EXIT WARNING** | Exhaustion বা divergence পাওয়া গেল | প্যাটার্ন বিবরণ, strength, দিক warning |
| **DAILY BIAS** | নতুন VP shape কম্পিউট হলো | Shape, দিক, confidence, POC/VAH/VAL, qualified levels |

### 📲 টেলিগ্রাম সেটআপ করার নিয়ম

1. Telegram-এ [@BotFather](https://t.me/botFather)-এ যান
2. `/newbot` কমান্ড দিন, একটি নাম দিন, bot token পাবেন
3. আপনার chat ID জানতে [@userinfobot](https://t.me/userinfobot)-এ মেসেজ করুন
4. এই দুটি তথ্য `config/settings.py`-তে বসান

---

## ১১. ডেটাবেস

সিস্টেমটি SQLite ডেটাবেস ব্যবহার করে (WAL মোডে — দ্রুত এবং concurrent অ্যাক্সেসের জন্য)।

### 🗄️ SQLite Schema (৫টি টেবিল)

```
┌─────────────────────────────────────────────────────────────────┐
│                    orderflow_data.db (WAL মোড)                   │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌────────────────┐ ┌──────────┐    │
│  │  ticks   │ │ candles  │ │ volume_profiles│ │ signals  │    │
│  ├──────────┤ ├──────────┤ ├────────────────┤ ├──────────┤    │
│  │ id (PK)  │ │ id (PK)  │ │ id (PK)        │ │ id (PK)  │    │
│  │instrument│ │instrument│ │ instrument     │ │instrument│    │
│  │timestamp │ │timestamp │ │ session_date   │ │timestamp │    │
│  │ price    │ │timeframe │ │ poc, vah, val  │ │sig_type  │    │
│  │ size     │ │ OHLCV    │ │ total_volume   │ │direction │    │
│  │ side     │ │ buy/sell │ │ shape          │ │price_lvl │    │
│  │ trade_id │ │ delta    │ │ poc_pos_pct    │ │ strength │    │
│  └──────────┘ │footprint │ │ lvn (JSON)     │ │details   │    │
│               └──────────┘ │ vol_at_price   │ │  (JSON)  │    │
│                             └────────────────┘ └──────────┘    │
│                                                                  │
│  ┌──────────────┐                                               │
│  │ trade_journal│                                               │
│  ├──────────────┤                                               │
│  │ id (PK)      │                                               │
│  │ instrument   │                                               │
│  │ direction    │                                               │
│  │ entry/exit   │                                               │
│  │  time (ms)   │                                               │
│  │ entry/exit   │                                               │
│  │  price       │                                               │
│  │ SL, TP       │                                               │
│  │ pnl_ticks    │                                               │
│  │ rr_ratio     │                                               │
│  │ signals(JSON)│                                               │
│  │ notes        │                                               │
│  └──────────────┘                                               │
│                                                                  │
│  Indexes: (instrument, timestamp), (instrument, session_date)   │
│  PRAGMA: journal_mode=WAL, synchronous=NORMAL                   │
└─────────────────────────────────────────────────────────────────┘
```

### 📋 টেবিলগুলোর কাজ

- **ticks:** প্রতিটি raw লেনদেন সংরক্ষণ (দাম, পরিমাণ, পক্ষ, সময়)
- **candles:** 1m ক্যান্ডেল ও footprint ডেটা
- **volume_profiles:** প্রতিটি সেশনের VP (POC, VAH, VAL, shape)
- **signals:** সব প্যাটার্ন সিগন্যাল ও তাদের বিস্তারিত তথ্য
- **trade_journal:** প্রতিটি ট্রেডের সম্পূর্ণ রেকর্ড (entry, exit, PnL, RR)

---

## ১২. ইনস্টলেশন (ধাপে ধাপে)

### ✅ প্রয়োজনীয়তা (Prerequisites)

- **Python 3.10 বা তার উপরের ভার্সন**
- **MetaTrader 5 টার্মিনাল** (শুধু MT5 ফিড ব্যবহার করলে) অথবা **Bybit** (ফ্রি, কোনো অ্যাকাউন্ট লাগে না)

### 🚀 সেটআপ

```bash
# ১. রিপোজিটরি clone করুন
git clone https://github.com/mahmoud20138/OrderFlow-Analysis-Pro.git
cd OrderFlow-Analysis-Pro

# ২. ডিপেন্ডেন্সি ইনস্টল করুন (দুটি উপায়)
# উপায় ১: pip install -e . (সুপারিশকৃত)
pip install -e .

# উপায় ২: ম্যানুয়ালি
pip install websockets aiohttp pandas numpy scipy \
    python-telegram-bot plotly kaleido aiosqlite pytz pyyaml
```

### 🟢 কুইক স্টার্ট: Bybit দিয়ে (সবচেয়ে সহজ — নতুনদের জন্য)

```bash
# ১. config/settings.py তে DATA_SOURCE = DataSource.BYBIT সেট করুন
# ২. সিস্টেম চালু করুন
python -m orderflow_system.main

# ৩. ব্রাউজারে ড্যাশবোর্ড খুলুন
# http://localhost:8080
```

### 🟡 কুইক স্টার্ট: MT5 দিয়ে

```bash
# ১. MetaTrader 5 টার্মিনাল খুলুন ও login করুন
# ২. config/settings.py তে আপনার MT5 credentials বসান:
#    MT5 = MT5Config(login=..., password="...", server="...")
# ৩. সিস্টেম চালু করুন
python -m orderflow_system.main
```

### 🔵 শুধু ড্যাশবোর্ড: ডেমো মোড

কোনো লাইভ ডেটা ছাড়াই শুধু ড্যাশবোর্ড চালাতে চাইলে (সবচেয়ে নিরাপদ, শেখার জন্য):

```bash
# Deterministic demo data দিয়ে ড্যাশবোর্ড
python -m orderflow_system.dashboard
```

---

## ১৩. কনফিগারেশন

সব কনফিগারেশন `orderflow_system/config/settings.py` ফাইলে আছে।

```python
# ডেটা সোর্স: "MT5", "BYBIT", বা "BOTH"
DATA_SOURCE = DataSource.BYBIT

# MT5 credentials (শুধু MT5 ফিড ব্যবহার করলে)
MT5 = MT5Config(
    login=12345678,
    password="your_password",
    server="YourBroker-Server",
    poll_interval_ms=100,       # Tick polling frequency
    enable_book=True,           # Market book (DOM) enable করুন
    download_history_days=3,    # Warmup-এর জন্য M1 history ডাউনলোড
)

# টেলিগ্রাম অ্যালার্ট
TELEGRAM = TelegramConfig(
    bot_token="your_bot_token",
    chat_id="your_chat_id",
    send_chart_snapshots=True,
)

# ড্যাশবোর্ড
DASHBOARD = DashboardConfig(
    enabled=True,
    host="0.0.0.0",
    port=8080,
    log_level="warning",
)

# ডেটাবেস
DB_PATH = "orderflow_data.db"
LOG_LEVEL = "INFO"
```

### 🎚️ Per-Instrument Threshold Tuning

প্রতিটি ইনস্ট্রুমেন্টের নিজস্ব tune করা thresholds আছে। NAS100-এর উদাহরণ:

```python
AbsorptionConfig(
    min_aggressive_volume=50,       # Absorption হিসেবে ধরার ন্যূনতম ভলিউম
    max_price_displacement_ticks=2, # দাম সর্বোচ্চ কত tick নড়তে পারবে
    rolling_window_seconds=30,      # Lookback window
    min_attempts=2,                 # একটি লেভেলে ন্যূনতম কতবার attempt
    big_trade_filter=10,            # "বড়" ট্রেড হিসেবে ধরার ভলিউম threshold
)

InitiativeConfig(
    min_delta_threshold=30,          # ন্যূনতম delta
    volume_acceleration_min=1.5,     # গড় ভলিউমের ১.৫ গুণ হতে হবে
    min_price_displacement_ticks=3,  # ন্যূনতম body size
    delta_price_alignment=True,      # Delta ও candle direction match করতে হবে
)
```

---

## ১৪. ব্যবহার পদ্ধতি

### ▶️ সিস্টেম চালু করুন

```bash
python -m orderflow_system.main
```

সিস্টেম চালু হলে যা যা ঘটবে:

1. ✅ কনফিগার করা ডেটা সোর্সে সংযুক্ত হবে
2. ✅ Historical bars ডাউনলোড করবে (MT5) বা live feed সংযুক্ত হবে (Bybit)
3. ✅ Historical ডেটা থেকে initial volume profiles তৈরি করবে
4. ✅ সব ২৯টি ইনস্ট্রুমেন্টের জন্য ৫টি প্যাটার্ন ডিটেক্টর চালু করবে
5. ✅ Daily bias ও qualified levels কম্পিউট করবে
6. ✅ শক্তিশালী লেভেলগুলো (strength ≥ 50) স্বয়ংক্রিয়ভাবে watch করবে
7. ✅ State machine monitoring শুরু করবে
8. ✅ সিগন্যাল পেলে টেলিগ্রামে অ্যালার্ট পাঠাবে
9. ✅ `http://localhost:8080`-এ ড্যাশবোর্ড সার্ভ করবে

### 🌐 ড্যাশবোর্ড Endpoints

```bash
# সব ইনস্ট্রুমেন্ট দেখুন
curl http://localhost:8080/api/instruments

# Scanner ranking (সব pair ট্রেড proximity অনুযায়ী)
curl http://localhost:8080/api/scanner

# NAS100-এর জন্য strategy status
curl http://localhost:8080/api/strategy-status/NAS100USDT

# Volume profile দেখুন
curl http://localhost:8080/api/volume-profile/NAS100USDT?days=5

# Daily bias দেখুন
curl http://localhost:8080/api/bias/NAS100USDT

# Signal history
curl http://localhost:8080/api/signals/NAS100USDT?limit=50

# Active trade state
curl http://localhost:8080/api/trade/NAS100USDT
```

---

## ১৫. প্রজেক্ট স্ট্রাকচার

```
orderflow_system/
├── main.py                          # সিস্টেম অর্কেস্ট্রেটর (666L)
├── __init__.py                      # প্যাকেজ init
├── test_integration.py              # Integration tests (314L)
│
├── config/
│   └── settings.py                  # ২৯টি ইনস্ট্রুমেন্ট কনফিগ, ১০টি কনফিগ ডেটাক্লাস (946L)
│
├── data/
│   ├── models.py                    # ৭টি ডেটাক্লাস: Tick, Candle, Signal... (290L)
│   ├── candle_builder.py            # Tick থেকে 1m candle aggregation (133L)
│   ├── bybit_feed.py                # Bybit WebSocket feed (209L)
│   ├── mt5_feed.py                  # MT5 terminal feed (495L)
│   └── database.py                  # SQLite persistence, ৫টি টেবিল (278L)
│
├── analytics/
│   ├── volume_profile.py            # POC, VAH, VAL, LVN, shape (258L)
│   ├── delta.py                     # Vertical, horizontal, cumulative delta (197L)
│   ├── footprint.py                 # Bid/ask per level, imbalance (181L)
│   └── orderbook.py                 # L2 depth, thin levels (208L)
│
├── patterns/
│   ├── absorption.py                # Effort >> result detection (257L)
│   ├── initiative.py                # Effort = result (momentum) (133L)
│   ├── sweep.py                     # Thin book displacement (142L)
│   ├── exhaustion.py                # Declining volume (228L)
│   └── divergence.py                # Price vs delta disagreement (159L)
│
├── signals/
│   ├── profile_framing.py           # Daily bias + qualified levels (343L)
│   └── aggregator.py                # State machine + composite scoring (516L)
│
├── alerts/
│   └── telegram_bot.py              # Telegram notifications (202L)
│
└── dashboard/
    ├── app.py                       # FastAPI REST + WebSocket (1015L)
    ├── websocket_manager.py         # ৯-চ্যানেল broadcast manager (186L)
    ├── demo_data.py                 # Demo data generator (782L)
    ├── __main__.py                  # Standalone launcher (35L)
    └── static/
        ├── index.html               # মেইন HTML shell (121L)
        ├── app.js                   # TradingView charts + WebSocket (939L)
        ├── style.css                # ড্যাশবোর্ড styling (566L)
        ├── footprint.js             # Canvas footprint chart (700L)
        ├── signals.js               # Signal cards (479L)
        ├── performance.js           # Performance analytics (599L)
        ├── orderbook.js             # Orderbook depth ladder (318L)
        ├── microstructure.js        # Microstructure indicators (417L)
        └── tape.js                  # Time & sales (281L)
```

### 📊 ফাইল ইনভেন্টরি

| ক্যাটাগরি | ফাইল সংখ্যা | Python Lines | JS/CSS/HTML Lines | মোট Lines |
|----------|-------|-------------|-------------------|-------------|
| Config | 1 | 946 | — | 946 |
| Data | 5 | 1,405 | — | 1,405 |
| Analytics | 4 | 844 | — | 844 |
| Patterns | 5 | 919 | — | 919 |
| Signals | 2 | 859 | — | 859 |
| Alerts | 1 | 202 | — | 202 |
| Dashboard | 4 + 8 static | 1,818 | 4,420 | 6,238 |
| Main + Tests | 2 | 980 | — | 980 |
| **মোট** | **~32** | **~7,973** | **~4,420** | **~12,393** |

---

## ১৬. API রেফারেন্স

### 🌐 REST Endpoints (১৬টি)

| Method | Endpoint | বর্ণনা |
|--------|----------|-------------|
| GET | `/` | ড্যাশবোর্ড UI |
| GET | `/api/instruments` | সক্রিয় ইনস্ট্রুমেন্ট (stats + trade phase সহ) |
| GET | `/api/scanner` | সব pair ট্রেড proximity অনুযায়ী sorted (priority 0-118) |
| GET | `/api/markers/{symbol}` | TradingView chart-এর জন্য signal markers |
| GET | `/api/candles/{symbol}` | OHLCV candle history (params: count, tf, range) |
| GET | `/api/volume-profile/{symbol}` | Volume profile + POC/VAH/VAL (params: days, range) |
| GET | `/api/bias/{symbol}` | Daily bias + qualified levels |
| GET | `/api/signals/{symbol}` | Signal history (params: limit) |
| GET | `/api/trade/{symbol}` | Active trade state |
| GET | `/api/strategy-status/{symbol}` | ৬-ধাপ Fabio methodology checklist |
| GET | `/api/orderbook/{symbol}` | বর্তমান L2 orderbook (params: levels) |
| GET | `/api/delta/{symbol}` | Cumulative delta history (params: count, tf, range) |
| GET | `/api/footprint/{symbol}` | Footprint chart data (params: tf, range) |
| GET | `/api/tape/{symbol}` | Time & sales (params: count) |
| GET | `/api/microstructure/{symbol}` | Microstructure snapshot |
| GET | `/api/stats` | সিস্টেম-wide stats |

### 🏷️ Strategy Status Labels

| Status | অর্থ |
|--------|---------|
| NO_DATA | এখনো কোনো ডেটা আসেনি |
| NO_LEVELS | কোনো qualified level চিহ্নিত হয়নি |
| WAITING_FOR_PRICE | Level আছে, কিন্তু দাম কাছে নেই |
| AT_LEVEL_SCANNING | দাম একটি qualified level-এর কাছে |
| WATCHING | Aggregator একটি level watch করছে |
| ENTRY_READY | Absorption পাওয়া গেছে, composite score ≥ threshold |
| IN_TRADE | পজিশন চালু |
| BREAK_EVEN | SL কে entry-তে নিয়ে যাওয়া হয়েছে |
| TRAILING | SL initiative-এ ট্রেইল করছে |
| IDLE | কোনো active monitoring নেই |

### 🎯 Scanner Priority Scoring

| State | Base Score | Bonus |
|-------|-----------|-------|
| IN_TRADE | 100 | +3 per completed step |
| TRAILING | 95 | +3 per completed step |
| BREAK_EVEN | 90 | +3 per completed step |
| ENTRY_READY | 85 | +3 per completed step |
| AT_LEVEL_SCANNING | 70 | +3 per completed step |
| WATCHING | 60 | +3 per completed step |
| WAITING_FOR_PRICE | 40 | — |
| NO_LEVELS | 20 | — |
| NO_DATA | 10 | — |
| OFFLINE | 5 | — |
| IDLE | 0 | — |

---

## ১৭. ডেমো মোড

সিস্টেমে একটি **deterministic demo data generator** আছে যা কোনো লাইভ ডেটা ছাড়াই সব ২৯টি ইনস্ট্রুমেন্টের জন্য বাস্তবসম্মত ডেটা তৈরি করে। চালানোর উপায়:

```bash
python -m orderflow_system.dashboard
```

### 🎨 ডেমো মোডে যা তৈরি হয়

- OHLCV candles (random walk, প্রতিটি symbol/timeframe-এর জন্য seeded)
- Volume profiles (Gaussian distributions সহ)
- Cumulative delta (bar-level noise সহ)
- Orderbooks (~১৫% thin levels সহ)
- ৬টি institutional-grade signal templates (narrative, thesis, edge, invalidation, HTF context, session, regime, MTF confluence, blockers, grade সহ)

### 🏆 Signal Quality Grading

| Grade | Score | অর্থ |
|-------|-------|---------|
| **A+** | ≥85 | অসাধারণ — একাধিক confirmation, উচ্চ confluence |
| **A** | ≥70 | শক্তিশালী — solid pattern + level + bias alignment |
| **B** | ≥55 | ভালো — pattern detected, partial confluence |
| **C** | <55 | দুর্বল — শুধু pattern, skip করা যেতে পারে |

### 📨 সিগন্যাল আউটপুট উদাহরণ

**Entry Signal:**
```
ENTRY SIGNAL: NAS100 LONG
  Composite Score: 72/100
  Pattern: ABSORPTION at VAL (17,845.50)
  Delta: +1,250 (buyers absorbing sells)
  Volume: 3.2x average
  Bias: P-shape (LONG), confidence 85%
  Entry: 17,846.00 | SL: 17,830.00 | TP: 17,878.00
  R:R: 1:2.0
  Grade: A
```

**Daily Bias Update:**
```
DAILY BIAS: NAS100
  Shape: P-shape (buyers in control)
  Direction: LONG | Confidence: 85%
  POC: 17,852.00 | VAH: 17,890.00 | VAL: 17,820.00
  LVN: [17,835.00, 17,868.00]
  Qualified Levels: VAL (buy, str=50), MERGED_VAL (buy, str=70)
```

**Strategy Status:**
```
STRATEGY STATUS: NAS100
  Step 1: Profile Framing    ✓ P-shape, LONG, 85%
  Step 2: Qualified Levels   ✓ VAL=17820, MERGED_VAL=17815
  Step 3: Price at Level     ✓ Price 17825 near VAL
  Step 4: Absorption Scan    ✓ Detected, strength 72
  Step 5: Entry Decision     ✓ Composite 72 ≥ 40
  Step 6: Trade Management   ⏳ Waiting for initiative
  Overall: ENTRY_READY
```

---

## ১৮. কম্পোজিট স্কোরিং সিস্টেম

`SignalAggregator` একটি composite score (0-100) কম্পিউট করে যা নির্ধারণ করে একটি signal ট্রেডে পরিণত হবে কিনা।

```
┌──────────────────────────────────────────────────────────┐
│              COMPOSITE SCORE CALCULATION                  │
│                                                          │
│  Signal Weight (প্যাটার্ন অনুযায়ী ভিন্ন):                   │
│  ┌────────────────┬────────┐                             │
│  │ Absorption     │  ×0.30 │  ← সর্বোচ্চ weight           │
│  │ Divergence     │  ×0.25 │                             │
│  │ Initiative     │  ×0.20 │                             │
│  │ Sweep          │  ×0.20 │                             │
│  │ Other          │  ×0.15 │                             │
│  └────────────────┴────────┘                             │
│                                                          │
│  Level Strength:     ×0.25                               │
│  Bias Alignment:     ×0.20 (দিক match করলে)              │
│  Bias WARNING:       -10   (VA reject হলে penalty)       │
│                                                          │
│  Final: clamped to [0, 100]                              │
│  Minimum to enter:   40 (configurable)                   │
└──────────────────────────────────────────────────────────┘
```

### 💰 SL/TP Calculation

| Scenario | SL (LONG) | TP (LONG) | SL (SHORT) | TP (SHORT) |
|----------|-----------|-----------|------------|------------|
| **Bias সহ** | `val - (vah-val)×0.1` | `vah` | `vah + (vah-val)×0.1` | `val` |
| **Bias ছাড়া** | `price × 0.997` (-0.3%) | `price × 1.006` (+0.6%) | `price × 1.003` (+0.3%) | `price × 0.994` (-0.6%) |

### 🔬 প্যাটার্ন ডিটেকশন কীভাবে কাজ করে

**Absorption Detection (২টি পদ্ধতি):**

```
পদ্ধতি ১: Delta/Close Mismatch
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Delta: +500 (ক্রয়)         Delta: -400 (বিক্রয়)
  Candle: RED (নিচে বন্ধ)     Candle: GREEN (উপরে বন্ধ)
  → বিক্রেতারা absorb করছে    → ক্রেতারা absorb করছে
  → Signal: SELL              → Signal: BUY

  Strength = (|delta| / min_aggressive_volume) * 40

পদ্ধতি ২: Level Absorption
━━━━━━━━━━━━━━━━━━━━━━━━━━
  প্রতিটি price level-এ rolling window-এ aggressive volume track করুন।
  যদি volume >= min_aggressive AND attempts >= min_attempts:
    → ABSORPTION signal
    Strength = (vol / min_aggressive) * 30 + attempts * 15
```

**Initiative Detection (৫টি ক্রাইটেরিয়া):**

```
┌──────────────────────────────────────────────────────────┐
│  INITIATIVE = Aggressive Conviction                      │
│                                                          │
│  সব ৫টি পূরণ করতে হবে:                                   │
│  ┌─────────────────────────────────────────────┐        │
│  │ ১. |delta| >= min_delta_threshold (30)       │  ✓/✗  │
│  │ ২. volume / avg >= volume_accel (1.5x)       │  ✓/✗  │
│  │ ৩. body_size >= min_displacement (3 ticks)   │  ✓/✗  │
│  │ ৪. delta direction == candle direction       │  ✓/✗  │
│  │ ৫. Bonus: one-sided imbalance prints (>3.0)  │  +10  │
│  └─────────────────────────────────────────────┘        │
│                                                          │
│  Strength = delta*20 + accel*15 + body*5 + imbalance*10 │
└──────────────────────────────────────────────────────────┘
```

---

## ১৯. কন্ট্রিবিউশন

আপনি এই প্রজেক্টে অবদান রাখতে পারেন! বিস্তারিত [CONTRIBUTING.md](CONTRIBUTING.md)-তে দেখুন।

### যেসব ক্ষেত্রে অবদান স্বাগত:

- **নতুন প্যাটার্ন ডিটেক্টর** — `patterns/` ডিরেক্টরিতে যোগ করুন
- **অতিরিক্ত ইনস্ট্রুমেন্ট** — `config/settings.py`-তে config যোগ করুন
- **ড্যাশবোর্ড উন্নয়ন** — frontend বা API উন্নতি
- **ডকুমেন্টেশন** — গাইড, টিউটোরিয়াল, API docs
- **Bug fix** — GitHub Issues দেখুন

### ডেভেলপমেন্ট সেটআপ

```bash
pip install -e ".[dev]"
```

### PR প্রক্রিয়া

১. Fork করুন
২. Feature branch তৈরি করুন (`git checkout -b feature/my-feature`)
৩. পরিবর্তন করুন
৪. Test চালান: `pytest orderflow_system/test_integration.py`
৫. Pull request পাঠান

### 📝 Code Style

- Python 3.10+ with type hints
- Dataclasses for data models
- Async/await for I/O operations
- প্রতিটি মডিউলে existing pattern follow করুন

---

## ২০. লাইসেন্স ও ডিসক্লেইমার

### 📄 লাইসেন্স

[MIT](LICENSE) — ব্যক্তিগত ও বাণিজ্যিক প্রজেক্টে স্বাধীনভাবে ব্যবহার করুন।

### ⚠️ ডিসক্লেইমার (খুব গুরুত্বপূর্ণ)

> **এই সফটওয়্যারটি শুধুমাত্র শিক্ষামূলক ও গবেষণার উদ্দেশ্যে।** এটি কোনো আর্থিক পরামর্শ নয়। ট্রেডিংয়ে ক্ষতির বড় ঝুঁকি থাকে। অতীত পারফরম্যান্স ভবিষ্যৎ ফলাফলের নিশ্চয়তা দেয় না। **নিজ দায়িত্বে ব্যবহার করুন।**

---

## 🎓 বিগিনারদের জন্য টিপস

১. **প্রথমে ডেমো মোডে শুরু করুন** — `python -m orderflow_system.dashboard` দিয়ে, কোনো রিয়েল টাকা ছাড়াই।
২. **প্রতিটি প্যাটার্ন আলাদাভাবে বুঝুন** — Absorption, Initiative, Sweep, Exhaustion, Divergence কীভাবে কাজ করে।
৩. **Volume Profile শিখুন** — POC, VAH, VAL, LVN কী, তা জানা অত্যন্ত জরুরি।
৪. **ছোট থেকে শুরু করুন** — লাইভ ট্রেড করার সময় সবচেয়ে ছোট size দিয়ে শুরু করুন।
৫. **টেলিগ্রাম অ্যালার্ট চালু রাখুন** — যাতে আপনি কোনো সিগন্যাল miss না করেন।
৬. **প্রতিটি ট্রেড journal করুন** — ভুল থেকে শেখার সবচেয়ে ভালো উপায়।
৭. **Fabio Testa-র মেথডলজি পড়ুন** — এই পুরো সিস্টেমটি তার উপর ভিত্তি করে তৈরি।

---

## 📚 আরও শেখার জন্য

- **Fabio Testa-র অর্ডারফ্লো মেথডলজি** — YouTube ও book আছে
- **Volume Profile Analysis** — Jim Dalton-র "Mind Over Markets" বইটি ক্লাসিক
- **Footprint Chart** — Bid/Ask imbalance কীভাবে কাজ করে
- **Orderbook Dynamics** — L2 depth ও liquidity কীভাবে দামকে প্রভাবিত করে

---

**শুভ কামনা! 🚀 যদি কোনো প্রশ্ন থাকে, GitHub Issues-এ জিজ্ঞাসা করুন।**
