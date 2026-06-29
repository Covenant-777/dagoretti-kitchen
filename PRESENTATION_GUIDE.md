# 🍰 Dagoretti Kitchen Incubator — Presentation Guide
## Student: Covenant Mimano | ADM: DCS-01-8594/2024

## 🔑 Baker 6-Digit PINs
| Baker | PIN |
|-------|-----|
| Amina Wanjiku | 123456 |
| Brian Otieno | 234567 |
| Carol Njeri | 345678 |
| David Kamau | 456789 |
| Esther Achieng | 567890 |
| Felix Mwangi | 678901 |
| Grace Moraa | 789012 |
| Hassan Abdi | 890123 |
| Irene Chebet | 901234 |
| James Ndegwa | 012345 |
| **Admin / Oven Manager** | **0000** |

## ▶ Before Presenting — Run These 2 Commands
```
python demo_setup.py
python app.py
```
Then open: http://127.0.0.1:5000

## Demo Steps
1. Baker Terminal → Enter 123456 → ENTER (login Amina)
2. Watch LCD update with elapsed time
3. Enter 123456 → ENTER again (logout + receipt shown)
4. Enter wrong PIN 3x → show lockout
5. Admin tab → PIN 0000 → show billing, chart, CSV export
