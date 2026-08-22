"""Vici client industry taxonomy (partner-classified at order submission)
and the mapping from industries to sensitive-context checks.

The taxonomy mirrors the order system's category list. Sensitive-context
derivation is prefix/name based and deliberately conservative: buyers
can always see which industries triggered which checks, and the check
wording stays observation-based either way.
"""

INDUSTRIES = [
    "01 Other- No Matching Category Below",
    "Adoption & Foster Care", "Adult Day Care", "Advertising", "Advocacy",
    "Agriculture - Tractors / Equipment / Farming / Seeding",
    "Airline Academy & Training", "Airports",
    "Alcohol - Bars / Breweries", "Alcohol - Wine & Spirits",
    "Alcohol - Winery", "Apps", "Arcade",
    "Arts - Performing Arts Center / Music Hall / Dance / Orchestra / Theatre",
    "Attractions - Halloween", "Attractions - Waterpark / Theme Park",
    "ATV Park/Trails", "Auctions", "Automobile - Golf Carts",
    "Automotive - Collision Center / Salvage / Auto Body Repair / Maintenance",
    "Automotive - Sports Vehicles / Motorcycles / Motor Sports",
    "Automotive - Automotive Accessories",
    "Automotive - Car Detailing and Automotive - Car Tinting",
    "Automotive - Car washing", "Automotive - Custom Car Design",
    "Automotive - Disabilities Mobility", "Automotive - Driving Education",
    "Automotive - Luxury", "Automotive - New or Used Cars",
    "Automotive - Parts & Services", "Automotive - Registration services",
    "Automotive - Rentals", "Automotive - RVs & Trailers",
    "Automotive - Smog / Emmissions", "Automotive - Tire Care",
    "Automotive - Windshield Installation and Replacement",
    "B2B - Business Solutions / Small Business Development",
    "B2B - Insurance Business Solutions",
    "B2B - Business IT / Communications / Security", "B2B - Business Supplies",
    "B2B - Coworking Space", "B2B - Events", "B2B - Food Retail",
    "B2B - Hospitality", "B2B - Other", "Bail Bonds",
    "Banking - Federal Credit Union / Bank", "Banking - Mortgages",
    "Banking - Personal / Title Loans", "Banking - Other",
    "Banking - Loans / Commercial Lending / Business Loans",
    "Banking - Short Term / High Interest Loan", "Boats", "Bowling Alleys",
    "Building Supplies", "Butcher", "Campground", "Casino",
    "Catering Services", "CBD", "Chamber of Commerce",
    "Child and Youth Services",
    "Child Care - Daycare / Day Camp / Summer Camp",
    "Children's Fun Center", "Chimney Cleaning", "Cleaning Service",
    "Clothing", "Coffee Shop",
    "Colleges & Universities - Advanced Degrees Masters / Graduate / MBA / PHD",
    "Colleges & Universities - Continuing Studies / Certificates",
    "Colleges & Universities - Sports Event",
    "Colleges & Universities - Undergraduate",
    "Commercial Roofing", "Community Centers", "Construction - Industrial",
    "Construction - Rentals / Machinery",
    "Construction - Supplies / Lumber / Building Materials",
    "Consumer Packaged Goods (CPG)", "Country Club",
    "Cryptocurrency / Bitcoin", "Dating Site / App", "Dentistry - Family",
    "Dentistry - General, Restorative, and Cosmetic",
    "Dentistry - Orthodontics", "Disability Services",
    "Education - Career Advancement", "Education - Enrichment Programs",
    "Education - Private or Public K-12 school", "Education - Religious",
    "Education - Recruitment", "Education - Vocational School", "Electronics",
    "Elevator Services", "Engineering", "Escape Room",
    "Event Planning & Catering", "Event Venue - Special Events",
    "Events - Conference", "Events - Expo", "Events - Festival",
    "Events - Holiday", "Events - Sports", "Events - Wedding",
    "Events - Concert", "Fabrication", "Family Support Services",
    "Farm - Apple Orchard", "Farmer's Market",
    "Financial Services - Tax Preparer",
    "Financial Services - Financial Advisor",
    "Financial Services - Investment Planning",
    "Financial Services - Residential Property Investor",
    "Financial Services - Fund Advisor",
    "Fire Protection", "Food - Organization", "Franchise Development",
    "Fundraising", "Funeral Services", "Furniture", "Furniture - Mattresses",
    "Furniture - Repair", "Gambling & Lotteries", "Generators",
    "Gentlemen's Club", "Go Karting", "Golf Club",
    "Government - Department of Education",
    "Government - Parks & Recreation Events",
    "Government - Town Events promotion", "Government - Census",
    "Government - Economic Development", "Government - Health / Safety",
    "Government - Political", "Government - Wildlife",
    "Government - Department of Public Works",
    "Greenhouses", "Grocery Store", "Gun Shop", "Hair & Beauty",
    "Health Services - Chiropractic", "Health Services - Hair Restoration",
    "Health Services - Hospice", "Health Services - Hospital",
    "Health Services - Maternity", "Health Services - Physical Therapy",
    "Health Services - Primary Care/Medical Group",
    "Health Services - Rehabilitation",
    "Health Services - Research / Medical Studies",
    "Health Services - Skincare", "Health Services - Urgent Care",
    "Health Services - Cancer", "Health Services - Weight Loss",
    "Health Services - Hearing / Vision", "Health Services - Heart & Lung",
    "Health Services - Medical Devices / Equipment / Software",
    "Health Services - Men's Health", "Health Services - Other",
    "Health Services - Fitness Club", "Health Services - Vascular & Vein",
    "Health Services - Home Care Services", "Health Services - Pediatrics",
    "Health Services - Pharmacy", "Health Services - Senior Living Facilities",
    "Health Services - Supplements", "Health Services - Women's Health",
    "Health Services - Podiatry", "Hearing Aids", "Hobbies",
    "Home - Construction & Renovation / Home Repair Contracting",
    "Home - Bathroom Supplies", "Home - Electrical", "Home - Fire Places",
    "Home - Flooring", "Home - Garage Door",
    "Home - Home & Garden Design / Home Exterior Products", "Home - Home Fuel",
    "Home - Home Installations", "Home - HVAC", "Home - Interior Design",
    "Home - Landscaping", "Home - Lighting", "Home - Patio / BBQ / Outdoors",
    "Home - Pools & Spas", "Home - Roofing & Insulation",
    "Home - Roofing, Siding, and Windows", "Home - Security", "Home - Septic",
    "Home - Shed / Garage Construction", "Home - Kitchen", "Home - Carpets",
    "Home - Fencing", "Hotel", "Hunting", "Insurance - Auto",
    "Insurance - Business", "Insurance - Health Insurance", "Insurance - Home",
    "Insurance - Life Insurance", "Insurance - Settlement",
    "Internal Media Promotion",
    "Internet & Phone - Internet Broadband Provider",
    "Internet & Phone - Authorized Dealer",
    "Internet & Phone - Internet, TV, and Phone Provider",
    "Internet & Phone - Mobile Phones / Plans",
    "Junk / Trash Removal", "Laundromat", "Lawn Care - Equipment",
    "Legal - Defense", "Legal - Fair claim", "Legal - Fire Relief",
    "Legal - Personal Injury", "Legal - Workers Comp", "Legal - Bankruptcy",
    "Legal - CPA", "Legal - Estate Planning", "Legal - Family Law",
    "Locksmith", "Manufacturing", "Marijuana / Cannabis", "Med Spa",
    "Medical - Blood/Lab", "Medical - Orthopedics", "Military",
    "Money Transfer Service", "Movie Theater", "Museum",
    "Musical Artist / Musician", "News", "Nonprofit",
    "Optometrist - Eyecare", "Painting - Residential & Commercial",
    "Pawn Shop", "Pest Control", "Pet Care",
    "Petroleum Provider / Bulk Fuel", "Photography", "Plumbing", "Podcasting",
    "Printing", "Psychic", "Public Adjuster", "Public Library",
    "Radio - Programming", "Real Estate - Apartment",
    "Real Estate - Commercial", "Real Estate - Home",
    "Real Estate - Luxury Apartments", "Real Estate - Management",
    "Real Estate - Property Management", "Real Estate - Property Inspections",
    "Real Estate - Agency", "Real Estate - Builders",
    "Real Estate - Investors", "Real Estate - Timeshares",
    "Real Estate - Mobile Homes",
    "Recreation or Entertainment Venue", "Recruitment", "Recycling",
    "Religion - Church / Place of Worship", "Restaurants - Casual Dining",
    "Restaurants - Chinese", "Restaurants - Farmers Market",
    "Restaurants - Fine Dining", "Restaurants - Food Delivery",
    "Restaurants - Ice Cream Parlor", "Restaurants - Mexican",
    "Restaurants - Pizza", "Restaurants - Restaurant Supplier",
    "Restaurants - Seafood", "Restaurants - Burgers",
    "Restaurants - Fast Food / Fast Casual", "Restaurants - Quick Service",
    "Restoration Services", "Retail - Adult Store", "Retail - Appliances",
    "Retail - Art", "Retail - Camera, Video", "Retail - Collectibles",
    "Retail - Convenience Stores", "Retail - Discount", "Retail - Flowers",
    "Retail - Footwear", "Retail - General / E-commerce", "Retail - Gift",
    "Retail - Household Cleaners / Laundry Supplies", "Retail - Jewelry",
    "Retail - Mall / Outlet Mall", "Retail - Office Supplies",
    "Retail - Shipping Center", "Retail - Sporting Goods",
    "Retail - Women's Clothing & Accessories", "Retail - Bicycle",
    "Retail - Books", "Retail - Toys",
    "Retail - Beef Food Products & Boutique",
    "Retirement Home", "Rock Climbing", "Salon & Spa", "Senior Care / Senior Living Community",
    "Sewing Machines", "Solar Power", "Spa & Massage", "Sporting Goods",
    "Sports - Ski / Snowboard", "Sports Betting", "Storage", "Tanning Salon",
    "Tattoo Parlor", "Technology", "Technology - Tech Services", "Therapy",
    "Tourism", "Towing", "Transportation - Limo",
    "Transportation - Moving Services", "Transportation - Shipping",
    "Transportation - Guided Tours", "Transportation - Public Transportation",
    "Transportation - Fleet", "Tree Service", "Truck Stop",
    "TV - Programming", "Unions", "Utilities - Energy / Water / Electric",
    "Vacation Rentals", "Vape Shop", "Veterans", "Veterinarian",
    "Virtual Reality Gaming Center", "Volunteer",
    "Waste Management/Utilities - Trash / Dumpster Rental", "Water Sports",
    "Water Well Builders", "Wedding", "Wholesale - Cleaning Supplies",
    "Tobacco", "E-Cigarettes", "Fireworks", "Sports Marketing / NIL",
    "Staffing", "Warehousing / Fulfillment", "Attractions - Circus",
    "Appliance Repair", "Raceway", "Attractions - Historical",
    "Estate Planning - Document Valut",
]

# industry -> sensitive context mapping (prefix or exact match)
_HEALTH_PREFIXES = ("Health Services", "Dentistry", "Medical -", "Med Spa",
                    "Therapy", "Optometrist", "Hearing Aids",
                    "Senior Care", "Retirement Home", "Adult Day Care",
                    "Insurance - Health")
_FINANCIAL_PREFIXES = ("Banking", "Financial Services", "Insurance -",
                       "Cryptocurrency", "Money Transfer")
_CHILDREN_EXACT = {"Child Care - Daycare / Day Camp / Summer Camp",
                   "Children's Fun Center", "Child and Youth Services",
                   "Retail - Toys"}


SENSITIVE_RULES = {
    "Healthcare": {
        "triggers": list(_HEALTH_PREFIXES),
        "kind": "prefix",
        "basis": "Most state privacy laws treat health data as sensitive, "
                 "requiring OPT-IN consent (not just an opt-out). Washington "
                 "and Nevada go further with separate consumer-health-data "
                 "laws - WA My Health My Data carries a private right of "
                 "action - which are health-specific and sit outside the "
                 "State targets list above. FTC actions (GoodRx, BetterHelp) "
                 "and the hospital pixel litigation wave target ad pixels on "
                 "health pages.",
        "scanner": "Fails when ad/analytics trackers fire ungated on a "
                   "declared health-context site; warns even when gated, "
                   "because sensitive-data opt-in quality needs review.",
    },
    "Financial services": {
        "triggers": list(_FINANCIAL_PREFIXES),
        "kind": "prefix",
        "basis": "GLBA covers customer financial data, and CFPB/FTC have "
                 "scrutinized pixels on loan and account pages. Several "
                 "state laws exempt GLBA-covered data but not the rest of "
                 "the site's tracking.",
        "scanner": "Warns when trackers fire without consent gating on a "
                   "declared financial-services site.",
    },
    "Children-directed": {
        "triggers": sorted(_CHILDREN_EXACT),
        "kind": "exact",
        "basis": "COPPA (federal) requires verifiable PARENTAL consent "
                 "before collecting personal information from under-13s - "
                 "a normal consent banner does not satisfy it. Behavioral "
                 "advertising to children is the FTC's most actively "
                 "enforced tracking rule.",
        "scanner": "Fails when ANY trackers are observed on a declared "
                   "child-directed site.",
    },
}


def derive_contexts(industries):
    """Map selected industries to sensitive-context check categories."""
    out = set()
    for ind in industries or []:
        if any(ind.startswith(p) for p in _HEALTH_PREFIXES):
            out.add("Healthcare")
        if any(ind.startswith(p) for p in _FINANCIAL_PREFIXES):
            out.add("Financial services")
        if ind in _CHILDREN_EXACT:
            out.add("Children-directed")
    return out
