# Fonti Dati e Strategie di Acquisizione — fanta-lab

fanta-lab combina 4 fonti dati eterogenee per costruire un profilo quantitativo a 360 gradi di ogni calciatore di Serie A.

---

## Tabella Riassuntiva delle Fonti

| Fonte | Dati Estratti | Metodo di Acquisizione | Copertura Storica |
|---|---|---|---|
| **fantacalcio.it** | Voti storici, Fantamedie, Gol, Assist, Rigori, Ammonizioni, Espulsioni, Quotazioni ufficiali, FVM | Scraping HTML (BeautifulSoup) + Parsing Excel | 11 stagioni (2015/16 - 2025/26) + Stagione Attuale |
| **Understat.com** | Expected Goals (xG), Expected Assists (xA), Non-penalty xG (npxG), Tiri p90, Passaggi chiave p90 | API REST interna (POST /main/getPlayersStats/) | Ultime 4 stagioni |
| **Transfermarkt.com** | Giorni totali di infortunio, numero stop, motivo infortunio, infortuni gravi | Scraping asincrono multithread (ThreadPoolExecutor) con cache JSON locale | Ultime 3 stagioni |
| **football-data.co.uk** | Risultati partite, tiri totali, tiri in porta, gol casa/trasferta | Download CSV diretto | Ultime 11 stagioni |

---

## Algoritmi di Risoluzione delle Entita' (Name Matching)

Le varie piattaforme utilizzano convenzioni differenti per i nomi dei calciatori (es. abbreviazioni, suffissi, caratteri accentati o apostrofi). fanta-lab implementa una pipeline di normalizzazione a quattro livelli:

1. **Normalizzazione Unicode (NFD)**: Rimozione di diacritici e accenti (es. Kessie -> kessie, Lauriente -> lauriente).
2. **Regex Stripping**: Rimozione automatica delle iniziali di nome (es. Martinez L. -> martinez, Paz N. -> paz).
3. **Fuzzy Matching con Levenshtein (difflib.get_close_matches)**: Confronto di similarita' con cutoff 0.75 - 0.85.
4. **Mappatura Manuale di Override (MANUAL_FUZZY_MAP)**: Dizionario esplicito per risolvere omonimie (es. fratelli Oyono A. / Oyono J., El Azzouzi A. / El Azzouzi O.).

---

## Best Practices di Scraping e Resilienza

- **User-Agent Desktop Header**: Emulazione di browser desktop per evitare blocchi IP.
- **Rate Limiting Controllato**: Pause di 1.5s tra le chiamate HTTP sequenziali.
- **Cache Locale Persistente**: File `tm_injuries_cache.json` salvato progressivamente ogni 30 record per evitare di ri-scaricare profili gia' acquisiti.
- **Fallback Automatico**: Se football-data e' irraggiungibile, gli indici offensivi e difensivi delle squadre vengono ricavati aggregando i gol segnati e subiti direttamente dai dati di `fantacalcio.it`.
