"""
Seed the reference/lookup tables:
  - All 28 states + 8 UTs
  - Major districts per state
  - Contact categories
Run once after schema creation.
"""

from database.models import get_engine, get_session, State, District, Category, create_all

# ─── States & UTs ─────────────────────────────────────────────────────────────

STATES = [
    # (name, code, capital, region, is_ut)
    ("Andhra Pradesh",      "AP",  "Amaravati",       "South",     False),
    ("Arunachal Pradesh",   "AR",  "Itanagar",        "Northeast", False),
    ("Assam",               "AS",  "Dispur",          "Northeast", False),
    ("Bihar",               "BR",  "Patna",           "East",      False),
    ("Chhattisgarh",        "CG",  "Raipur",          "Central",   False),
    ("Goa",                 "GA",  "Panaji",          "West",      False),
    ("Gujarat",             "GJ",  "Gandhinagar",     "West",      False),
    ("Haryana",             "HR",  "Chandigarh",      "North",     False),
    ("Himachal Pradesh",    "HP",  "Shimla",          "North",     False),
    ("Jharkhand",           "JH",  "Ranchi",          "East",      False),
    ("Karnataka",           "KA",  "Bengaluru",       "South",     False),
    ("Kerala",              "KL",  "Thiruvananthapuram","South",   False),
    ("Madhya Pradesh",      "MP",  "Bhopal",          "Central",   False),
    ("Maharashtra",         "MH",  "Mumbai",          "West",      False),
    ("Manipur",             "MN",  "Imphal",          "Northeast", False),
    ("Meghalaya",           "ML",  "Shillong",        "Northeast", False),
    ("Mizoram",             "MZ",  "Aizawl",          "Northeast", False),
    ("Nagaland",            "NL",  "Kohima",          "Northeast", False),
    ("Odisha",              "OD",  "Bhubaneswar",     "East",      False),
    ("Punjab",              "PB",  "Chandigarh",      "North",     False),
    ("Rajasthan",           "RJ",  "Jaipur",          "North",     False),
    ("Sikkim",              "SK",  "Gangtok",         "Northeast", False),
    ("Tamil Nadu",          "TN",  "Chennai",         "South",     False),
    ("Telangana",           "TS",  "Hyderabad",       "South",     False),
    ("Tripura",             "TR",  "Agartala",        "Northeast", False),
    ("Uttar Pradesh",       "UP",  "Lucknow",         "North",     False),
    ("Uttarakhand",         "UK",  "Dehradun",        "North",     False),
    ("West Bengal",         "WB",  "Kolkata",         "East",      False),
    # Union Territories
    ("Andaman & Nicobar",   "AN",  "Port Blair",      "Island",    True),
    ("Chandigarh",          "CH",  "Chandigarh",      "North",     True),
    ("Dadra & Nagar Haveli","DH",  "Silvassa",        "West",      True),
    ("Daman & Diu",         "DD",  "Daman",           "West",      True),
    ("Delhi",               "DL",  "New Delhi",       "North",     True),
    ("Lakshadweep",         "LD",  "Kavaratti",       "Island",    True),
    ("Puducherry",          "PY",  "Puducherry",      "South",     True),
    ("Jammu & Kashmir",     "JK",  "Srinagar/Jammu",  "North",     True),
    ("Ladakh",              "LA",  "Leh",             "North",     True),
]

# Major districts per state (abbreviated - extend as needed)
DISTRICTS = {
    "Maharashtra": ["Mumbai City","Mumbai Suburban","Pune","Nagpur","Nashik","Aurangabad",
                    "Solapur","Thane","Kolhapur","Satara","Sangli","Ahmednagar","Jalgaon",
                    "Amravati","Nanded","Latur","Osmanabad","Beed","Yavatmal","Wardha"],
    "Uttar Pradesh": ["Lucknow","Kanpur Nagar","Agra","Varanasi","Allahabad","Meerut",
                      "Ghaziabad","Gautam Buddha Nagar","Mathura","Ayodhya","Gorakhpur",
                      "Bareilly","Aligarh","Moradabad","Saharanpur","Muzaffarnagar"],
    "Karnataka": ["Bengaluru Urban","Bengaluru Rural","Mysuru","Hubballi-Dharwad","Mangaluru",
                  "Belagavi","Kalaburagi","Tumakuru","Shivamogga","Davanagere","Vijayapura",
                  "Ballari","Raichur","Bidar","Bagalkot","Hassan","Chikkamagaluru"],
    "Tamil Nadu": ["Chennai","Coimbatore","Madurai","Tiruchirappalli","Salem","Tirunelveli",
                   "Erode","Vellore","Thanjavur","Tiruppur","Dindigul","Ranipet","Kancheepuram",
                   "Villupuram","Cuddalore","Nagapattinam","Dharmapuri","Krishnagiri"],
    "West Bengal": ["Kolkata","Howrah","North 24 Parganas","South 24 Parganas","Darjeeling",
                    "Jalpaiguri","Asansol-Paschim Bardhaman","Birbhum","Murshidabad",
                    "Nadia","Hooghly","Malda","Cooch Behar","Siliguri"],
    "Delhi": ["Central Delhi","East Delhi","New Delhi","North Delhi","North East Delhi",
              "North West Delhi","Shahdara","South Delhi","South East Delhi","South West Delhi","West Delhi"],
    "Gujarat": ["Ahmedabad","Surat","Vadodara","Rajkot","Bhavnagar","Gandhinagar","Jamnagar",
                "Junagadh","Anand","Navsari","Mehsana","Patan","Banaskantha","Sabarkantha"],
    "Rajasthan": ["Jaipur","Jodhpur","Kota","Ajmer","Bikaner","Udaipur","Alwar","Bharatpur",
                  "Sikar","Sri Ganganagar","Tonk","Bundi","Chittorgarh","Dungarpur"],
    "Madhya Pradesh": ["Bhopal","Indore","Gwalior","Jabalpur","Ujjain","Sagar","Rewa",
                       "Satna","Dewas","Ratlam","Chhindwara","Mandsaur","Vidisha"],
    "Bihar": ["Patna","Gaya","Muzaffarpur","Bhagalpur","Darbhanga","Nalanda","Begusarai",
              "Rohtas","Munger","Purnia","Siwan","Samastipur","Sitamarhi","Araria"],
    "Andhra Pradesh": ["Visakhapatnam","Vijayawada","Guntur","Nellore","Kurnool","Tirupati",
                       "Kakinada","Rajahmundry","Ongole","Anantapur","Eluru","Chittoor"],
    "Telangana": ["Hyderabad","Warangal","Nizamabad","Khammam","Karimnagar","Nalgonda",
                  "Adilabad","Mahabubnagar","Sangareddy","Medak","Ranga Reddy"],
    "Kerala": ["Thiruvananthapuram","Kochi","Kozhikode","Thrissur","Kollam","Kannur",
               "Palakkad","Alappuzha","Malappuram","Kottayam","Idukki","Pathanamthitta"],
    "Haryana": ["Faridabad","Gurugram","Rohtak","Hisar","Panipat","Ambala","Karnal",
                "Sonipat","Yamunanagar","Panchkula","Bhiwani","Rewari","Sirsa"],
    "Punjab": ["Ludhiana","Amritsar","Jalandhar","Patiala","Bathinda","Mohali","Pathankot",
               "Hoshiarpur","Sangrur","Ferozepur","Faridkot","Moga","Muktsar"],
    "Odisha": ["Bhubaneswar","Cuttack","Rourkela","Berhampur","Sambalpur","Balasore",
               "Bhadrak","Koraput","Rayagada","Kendujhar","Sundargarh","Ganjam"],
    "Jharkhand": ["Ranchi","Dhanbad","Jamshedpur","Bokaro","Deoghar","Hazaribagh",
                  "Giridih","Dumka","Chaibasa","Palamu","Lohardaga","Gumla"],
    "Assam": ["Guwahati","Dibrugarh","Silchar","Jorhat","Nagaon","Tezpur","Tinsukia",
              "Bongaigaon","Goalpara","Kamrup","Cachar","Sivasagar"],
    "Chhattisgarh": ["Raipur","Bilaspur","Durg","Bhilai","Korba","Rajnandgaon","Jagdalpur",
                     "Ambikapur","Raigarh","Mahasamund","Dhamtari","Kawardha"],
    "Uttarakhand": ["Dehradun","Haridwar","Nainital","Udham Singh Nagar","Almora",
                    "Pauri Garhwal","Tehri Garhwal","Champawat","Pithoragarh","Chamoli"],
    "Himachal Pradesh": ["Shimla","Kangra","Mandi","Solan","Kullu","Una","Hamirpur",
                         "Chamba","Bilaspur","Sirmaur","Kinnaur","Lahaul & Spiti"],
}

# ─── Categories ───────────────────────────────────────────────────────────────

CATEGORIES = [
    # (slug, name, name_hi, icon, description, parent_slug)
    ("health",       "Health & Medical",      "स्वास्थ्य",      "🏥", "Hospitals, CMO, NHM, AIIMS", None),
    ("education",    "Education",             "शिक्षा",         "🎓", "Schools, colleges, DEO, UGC", None),
    ("police",       "Police & Law",          "पुलिस",          "🚔", "SP, DGP, CBI, courts",        None),
    ("revenue",      "Revenue & Land",        "राजस्व",         "📋", "Tehsildar, DM, land records", None),
    ("water",        "Water & Sanitation",    "जल",             "💧", "PHE, Jal Jeevan Mission",     None),
    ("electricity",  "Electricity & Power",   "बिजली",          "⚡", "DISCOM, State electricity boards", None),
    ("transport",    "Transport & Roads",     "परिवहन",         "🚌", "RTO, NHAI, PWD, railways",    None),
    ("agriculture",  "Agriculture & Farming", "कृषि",           "🌾", "KVK, NABARD, block agriculture", None),
    ("social",       "Social Welfare",        "समाज कल्याण",    "🤝", "ICDS, SC/ST welfare, OBC",    None),
    ("environment",  "Environment & Forest",  "पर्यावरण",       "🌳", "Forest dept, PCB, CPCB",      None),
    ("labour",       "Labour & Employment",   "श्रम",           "⚒️", "Labour office, ESI, PF",      None),
    ("women",        "Women & Child Dev.",    "महिला एवं बाल",  "👩", "Anganwadi, ICDS, WCD",        None),
    ("finance",      "Finance & Banking",     "वित्त",          "🏦", "Treasury, RBI, NABARD",       None),
    ("housing",      "Housing & Urban Dev.",  "आवास",           "🏠", "PMAY, HUDCO, municipality",   None),
    ("disaster",     "Disaster Management",   "आपदा प्रबंधन",   "🆘", "NDRF, SDRF, DM office",       None),
    ("grievance",    "Public Grievance",      "शिकायत",         "📩", "CPGRAMS, RTI, Lokayukta",     None),
]


# ─── Seeder ───────────────────────────────────────────────────────────────────

def seed_all(db_url: str = None):
    engine = get_engine(db_url)
    create_all(engine)
    session = get_session(engine)

    try:
        # ── States
        state_map = {}
        for name, code, capital, region, is_ut in STATES:
            existing = session.query(State).filter_by(code=code).first()
            if not existing:
                s = State(name=name, code=code, capital=capital, region=region, is_ut=is_ut)
                session.add(s)
                session.flush()
                state_map[name] = s.id
                print(f"  + State: {name}")
            else:
                state_map[name] = existing.id

        session.commit()
        print(f"✅ {len(STATES)} states seeded.")

        # Re-fetch state map (ids after commit)
        all_states = {s.name: s.id for s in session.query(State).all()}

        # ── Districts
        dist_count = 0
        for state_name, districts in DISTRICTS.items():
            sid = all_states.get(state_name) or all_states.get(state_name.replace("Delhi","Delhi"))
            if not sid:
                # Try partial match
                for sn, si in all_states.items():
                    if state_name.lower() in sn.lower():
                        sid = si
                        break
            if not sid:
                print(f"  ⚠ State not found: {state_name}")
                continue
            for dname in districts:
                existing = session.query(District).filter_by(state_id=sid, name=dname).first()
                if not existing:
                    session.add(District(state_id=sid, name=dname))
                    dist_count += 1

        session.commit()
        print(f"✅ {dist_count} districts seeded.")

        # ── Categories
        slug_to_id = {}
        for slug, name, name_hi, icon, desc, parent_slug in CATEGORIES:
            existing = session.query(Category).filter_by(slug=slug).first()
            if not existing:
                c = Category(slug=slug, name=name, name_hi=name_hi, icon=icon, description=desc)
                session.add(c)
                session.flush()
                slug_to_id[slug] = c.id
            else:
                slug_to_id[slug] = existing.id

        session.commit()
        print(f"✅ {len(CATEGORIES)} categories seeded.")

    except Exception as e:
        session.rollback()
        print(f"❌ Seed error: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    import os
    seed_all(os.getenv("DATABASE_URL"))
