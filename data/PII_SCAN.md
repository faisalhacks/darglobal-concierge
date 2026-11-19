# PII scan — 2026-11-19T11:15:10+00:00

Dataset: `data/concierge.sqlite` version `20261119-e5604e7e`

Patterns: Saudi mobile (05xxxxxxxx / +9665xxxxxxxx), any +international 9-14 digits, 10-digit 0-prefixed numbers, email addresses, wa.me / 'whatsapp <digits>'. Arabic-Indic digits normalised before matching. Also checks that no agent/owner/phone/email/whatsapp column exists in projects/listings.

Columns scanned: projects(name_en,name_ar,developer,description_en,description_ar,status), listings(title,district), pages(title,text), chunks(text).

**Hits in concierge.sqlite: 0**
**Hits in fixtures/mini.sqlite: 0**


Fields never extracted at source (by design): leadContactInfo, propertyOwner, contactDetails, ownerName, resEmployee, managedBy (person/agency names), REGA licence numbers.

DarGlobal manual extracts: names were already replaced with '[name removed]' and phone numbers with '[phone]' at collection time; both placeholders are dropped. From JSON-LD only GeoCoordinates and amenityFeature names are read; Organization founder/person, contactPoint and address nodes are never ingested. Contact pages (page_type='contact') hold one line of text and no phone, email or WhatsApp.
