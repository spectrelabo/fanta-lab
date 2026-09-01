# Metodologia di Calcolo dello Score Composito — fanta-lab

Lo **Score Composito** di `fanta-lab` è una metrica sintetica normalizzata nell'intervallo $[0.00, 1.00]$ che misura il valore atteso di un calciatore per l'asta del Fantacalcio, bilanciando rendimento storico, potenziale offensivo, integrità fisica ed efficienza di costo.

---

## 📐 Formula Generale

$$\text{Score}_{\text{base}} = \sum_{i} w_i \cdot \text{Norm}(F_i)$$

$$\text{Score}_{\text{finale}} = \text{Score}_{\text{base}} \times \left(1.0 - 0.15 \times \text{Malus}_{\text{infortuni}}\right)$$

---

## ⚖️ Pesi delle Feature ($w_i$)

| Feature ($F_i$) | Peso ($w_i$) | Descrizione | Motivazione |
|---|---|---|---|
| **MV Ponderata (3y)** | `0.20` | Media Voto ultimi 3 anni (pesi decrescenti 3×, 2×, 1×) | Cattura la costanza di prestazione pura depurata da exploit isolati. |
| **MV Attesa Stagionale** | `0.20` | Media Voto stimata dal modello algoritmico per la stagione | Proietta il rendimento nel contesto tattico attuale. |
| **Fantavoto Atteso** | `0.15` | Fantamedia attesa (voto base + bonus/malus) | Quantifica il potenziale realizzativo e di assist. |
| **Probabilità Bonus ≥ 8** | `0.20` | Probabilità di ottenere un punteggio $\ge 8.0$ a giornata | Premia i giocatori capaci di decidere le giornate (match-winner). |
| **xG Medio (3y)** | `0.10` | Expected Goals medi per stagione da Understat | Identifica la qualità e quantità delle occasioni create/ricevute. |
| **Disponibilità %** | `0.10` | Percentuale presenze a voto su 38 giornate teoriche | Valuta l'affidabilità nelle rotazioni e titolarità. |
| **Convenienza Prezzo** | `0.05` | $1.0 - \text{Norm}(\text{Prezzo})$ (inversamente prop.) | Favorisce i profili a basso costo con alto rendimento potenziale (low-cost gems). |

---

## 🩹 Modellazione del Rischio Infortuni ($\text{Malus}_{\text{infortuni}}$)

Il malus infortuni penalizza i calciatori soggetti a frequenti stop fisici, riducendo lo score finale fino a un massimo del **15%**:

$$\text{Penalità}_{\text{giorni}} = \min\left(\frac{\text{Giorni Stop 3y}}{180}, 1.0\right)$$

$$\text{Penalità}_{\text{grave}} = \begin{cases} 0.30 & \text{se } \text{Max Giorni Singolo Stop} \ge 60 \\ 0.00 & \text{altrimenti} \end{cases}$$

$$\text{Malus}_{\text{infortuni}} = \min\left(0.70 \cdot \text{Penalità}_{\text{giorni}} + \text{Penalità}_{\text{grave}}, 1.0\right)$$

### Impatto sull'Asta:
- Calciatori con **integrità perfetta** ($\text{Malus} = 0.00$): Mantengono il 100% del loro score potenziale.
- Calciatori con **alta fragilità** ($\text{Malus} = 1.00$): Subiscono un taglio secco del -15% sullo score, abbassando la priorità di rilancio all'asta.

---

## 🔄 Normalizzazione Min-Max Robusta

Ogni feature continua $X$ viene scalata tramite:

$$\text{Norm}(X) = \frac{X - \min(X)}{\max(X) - \min(X)}$$

In caso di valori mancanti ($NaN$), vengono applicati valori neutrali di imputazione (es. $0.75$ per disponibilità, $0.0$ per metriche avanzate xG non disponibili per neopromossi o nuovi arrivi).
