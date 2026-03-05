VENV_NAME ?= yt
VENV_BIN := $(VENV_NAME)/bin

.PHONY: venv install bq-setup fetch-comments fetch-comments-channel curate-comments run-inference streamlit clear-insights

venv:
	python -m venv $(VENV_NAME)

install:
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install -r requirements.txt

bq-setup:
	$(VENV_BIN)/python -m backend.config.setup_bigquery

fetch-comments:
	@if [ -z "$(VIDEO_ID)" ]; then echo "Usage: make fetch-comments VIDEO_ID=<video_id>"; exit 1; fi
	$(VENV_BIN)/python -m backend.ingestion.fetch_youtube_comments --video-id $(VIDEO_ID)

fetch-comments-channel:
	@if [ -z "$(CHANNEL_ID)" ]; then echo "Usage: make fetch-comments-channel CHANNEL_ID=<channel_id> [MAX_VIDEOS=N]"; exit 1; fi
	$(VENV_BIN)/python -m backend.ingestion.fetch_youtube_comments --channel-id $(CHANNEL_ID) --max-videos $(or $(MAX_VIDEOS),10)

curate-comments:
	$(VENV_BIN)/python -m backend.ingestion.curate_comments --limit $(or $(LIMIT),5000)

run-inference:
	@if [ -z "$(VIDEO_ID)" ]; then echo "Usage: make run-inference VIDEO_ID=<video_id>"; exit 1; fi
	$(VENV_BIN)/python -m backend.inference.comment_insights --video-id $(VIDEO_ID)

streamlit:
	$(VENV_BIN)/streamlit run frontend/app.py

# Tüm inference kayıtlarını siler (temiz başlangıç). Geri alınamaz.
clear-insights:
	$(VENV_BIN)/python -m backend.config.clear_insights

