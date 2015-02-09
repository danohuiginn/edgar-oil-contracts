
BUCKET=s3://sec-mining.openoil.net
CONF_FILE=mrjob.conf

_make_listing:
	python generate_input.py
	rm -rf tasks
	mkdir tasks
	split -l 10 listing.txt tasks/listing

test_import:
	python import_filings.py --cleanup=NONE --no-output <test_listing.txt

test_sic_filter:
	python sic_filter_filings.py --cleanup=NONE --no-output <filings.txt

test_score:
	python score_filings.py --cleanup=NONE --no-output <filings.txt

import:
	python import_filings.py -r emr \
		--conf-path $(CONF_FILE) \
		--output-dir=$(BUCKET)/filings-13xx/ \
		--no-output \
		$(BUCKET)/tasks/

sic_filter:
	python sic_filter_filings.py -r emr \
		--conf-path $(CONF_FILE) \
		--output-dir=$(BUCKET)/filings-13xx/ \
		--no-output \
		$(BUCKET)/filings-all/

score:
	python score_filings.py -r emr \
		--conf-path $(CONF_FILE) \
		--output-dir=$(BUCKET)/scores/ \
		--no-output \
		--file searches.txt --file stopwords.txt \
		$(BUCKET)/filings-sample/


make_listing:
	rm -rf tasks
	mkdir tasks
	python generate_input.py | split -l 10 - tasks/listing
	aws s3 sync ./tasks/ $(BUCKET)/tasks/

index_files:
	python edgar_indices.py
	aws s3 sync ./company_listings $(BUCKET)/company_listings

filter_filings:
	python filter_filings.py
	aws s3 sync ./company_listings_filtered $(BUCKET)/company_listings_filtered

sic_companies:
	python companis_by_sic.py \
		--conf-path $(CONF_FILE) \
		--no-output \
		--runner local \
		--cleanup NONE \
		-v \
		--emr-job-flow-id j-HRW9YVFAQ91Y\
		--output-dir=$(BUCKET)/moresics4 < sics.txt

minerals_reports:
	# zless company_listings/master_2014_* | grep "|SD|" > sd_filings.txt
	aws s3 sync ./sdfilings $(BUCKET)/minerals_reports
dl_filings_test:
	head -20 filings_by_company.txt | python dl_filings.py

dl_filings:
	cat filings_by_company.txt | python dl_filings.py
