# 🧠 Fine-Tuning FantaLab Copilot (Ollama + Qwen 2.5 3B)

Guida pratica per creare ed eseguire un modello locale ultra-rapido specializzato su VORP, aste matematiche e Fantacalcio Serie A.

---

## 1. Utilizzo Diretto Senza Fine-Tuning (Modelfile Ollama)

Se hai già **Ollama** installato, puoi creare immediatamente l'agente custom ottimizzato con zero addestramento:

```bash
# 1. Scarica il base model veloce (circa 1.9 GB)
ollama pull qwen2.5:3b

# 2. Compila il modello custom FantaLab usando il nostro Modelfile
cd fanta-lab
ollama create fanta-copilot -f copilot/Modelfile

# 3. Testa il modello in terminale
ollama run fanta-copilot "Confronta Lautaro Martinez e Thuram"
```

Per farlo utilizzare automaticamente dall'app web:
Nel file `.env` imposta:
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=fanta-copilot
```

---

## 2. Generazione del Dataset di Fine-Tuning (LoRA / SFT)

Per addestrare i pesi veri e propri con gergo, stime e confronti specifici:

```bash
# Genera il dataset JSONL con oltre 300 esempi istruzione/risposta
python3 copilot/training_data/generate_finetune_dataset.py
```

Il file `copilot/training_data/fanta_copilot_train.jsonl` verrà creato automaticamente.

### Addestramento con Unsloth / Hugging Face LoRA:
```python
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

max_seq_length = 2048
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-3B-Instruct",
    max_seq_length=max_seq_length,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0,
)

# Carica dataset ed esegui trainer
# Poi salva in formato GGUF per Ollama:
# model.save_pretrained_gguf("fanta-copilot-q4", tokenizer, quantization_method="q4_k_m")
```
