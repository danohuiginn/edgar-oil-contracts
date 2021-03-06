import argparse
import codecs
import os
import re, math, string
from urlparse import urljoin
from unicodedata import normalize as ucnorm, category
from collections import defaultdict

from dissect.util.pdftext import pdf2text
from dissect.util.findcountries import countries_from_text

from mrjob.job import MRJob, JSONProtocol
from mrjob.protocol import JSONValueProtocol

DOCS = re.compile(r'^<DOCUMENT>$(.*)^</DOCUMENT>$', re.I | re.M | re.S)
SIC_EXTRACT = re.compile(r'<ASSIGNED-SIC> *(.*)', re.I)
AN_EXTRACT = re.compile(r'<ACCESSION-NUMBER> *(.*)', re.I)
CIK_EXTRACT = re.compile(r'<CIK> *(.*)', re.I)
FILENAME_EXTRACT = re.compile(r'<FILENAME> *(.*)', re.I)
CN_EXTRACT = re.compile(r'<CONFORMED-NAME> *(.*)', re.I)
TYPE_EXTRACT = re.compile(r'<TYPE> *(.*)', re.I)
REMOVE_SPACES = re.compile(r'\s+')

URL = 'http://www.sec.gov/Archives/edgar/data/%s/%s/%s-index.htm'


from boto.s3.connection import S3Connection
from boto.s3.key import Key
from settings import access_id, secret_id


def decompose_s3_url(url):
    parts = url.split('/', 3)
    bucket = parts[2]
    key = '/' + parts[3]
    return (bucket, key)


def makesearchregex(fn='searches.txt'):
    scores = {}
    for line in open(fn).readlines():
        term, score = line.rsplit(',', 1)
        term = term.lower().strip()
        if term.startswith('#'):
            continue
        scores[term] = re.compile(term), float(score)

    searches = re.compile(' (%s) ' % '|'.join(scores.keys()))
    return searches, scores



def normalize_text(text, lowercase=True):
    if not isinstance(text, unicode):
        text = unicode(text, errors='ignore')
    chars = []
    # http://www.fileformat.info/info/unicode/category/index.htm
    for char in ucnorm('NFKD', text):
        cat = category(char)[0]
        if cat in ['C', 'Z', 'S']:
            chars.append(u' ')
        elif cat in ['M', 'P']:
            continue
        else:
            chars.append(char)
    text = u''.join(chars)
    text = REMOVE_SPACES.sub(' ', text)
    text = text.strip()
    if lowercase:
        text = text.lower()
    return text


def get_tokens(text, stopwords):
    tokens = []
    for token in text.split():
        if token in stopwords:
            continue
        if string.digits in token:
            continue
        tokens.append(token)
    return tokens



def sterms():
    SEARCHTERM_FILE='/tmp/searchterms.txt'

class OOMRJob(MRJob):

    def mapper_init(self):
        #s3 connection
        self.s3conn = S3Connection(access_id, secret_id)
    

class MRScoreFiles(OOMRJob):
    """
    input a list of filepaths
    output a list of filepaths which score above the threshold
    """
    THRESHOLD=10
    OUTPUT_PROTOCOL = JSONValueProtocol

    def configure_options(self):
        super(MRScoreFiles, self).configure_options()
        self.add_passthrough_option(
            '--watershed', default='/tmp/watershed.txt',
            help='File containing watershed list')
        self.add_passthrough_option(
            '--stopwords', default='/tmp/stopwords.txt',
            help='File containing stopword list')
        self.add_passthrough_option(
            '--pdf_input', action='store_true', default=False,
            help='Input files are pdf files -- extract text before processing')

    def mapper_init(self):
        self.stopwords = set(open(self.options.stopwords).read().lower().split())
        self.searches, self.scores = makesearchregex(self.options.watershed)

        OOMRJob.mapper_init(self)


    def compute_score(self, doc):
        text = normalize_text(doc)
        terms = defaultdict(int)
        pos_terms = set()
        score = 0.0

        tokens = max(1, len(get_tokens(text, self.stopwords)))

        # bias for longer documents:
        #tokens = tokens / 10

        textlen = float(max(1, len(text)))
        if textlen > 100:
            for match in self.searches.finditer(text):
                term = match.group(1)
                weight = None
                if term in self.scores:
                    _, weight = self.scores[term]
                else:
                    for term_, (rex, weight_) in self.scores.items():
                        if rex.match(term):
                            weight = weight_
                            term = term_
                            break

                if weight is None:
                    continue

                if weight > 0:
                    pos_terms.add(term)

                pos = float(match.start(1)) / textlen
                score += (weight * (math.log(pos) * -1.0)) + weight
                #print weight, score
                #print match.group(1), weight, score
                terms[term] += 1

        #print score, terms
        # weight for variety:
        #score = ((score * len(pos_terms)) / tokens)
        # score = score
        return score, tokens, len(pos_terms), dict(terms)

    def country_names(self, text):
        text = normalize_text(text) # XXX avoid this repetition
        return {'country_names': countries_from_text(text)}

    def snippet(self, filetext):
        return {'extract' : normalize_text(filetext)[:200]}

    def s3open(self, filepath):
        bucketname, keyname = decompose_s3_url(filepath)
        bucket = self.s3conn.get_bucket(bucketname)
        key = Key(bucket)
        key.key = keyname
        as_string = key.get_contents_as_string()
        return as_string

    def text_from_file(self, filepath):
        if self.options.pdf_input:
            return pdf2text(filepath)
        elif 's3://' in filepath:
            return self.s3open(filepath)
        else:
            return codecs.open(filepath, 'r', 'utf-8').read()

    def mapper(self, _, filepath):
        filetext = self.text_from_file(filepath)
        score, tokens, numpositive, dictpositive = self.compute_score(filetext)
        if score > self.THRESHOLD:
            output = {
                'score': score,
                'filepath': filepath,
                'positives': dictpositive
                }
            output.update(self.country_names(filetext))
            output.update(self.snippet(filetext))
            yield None, output

class MRScoreFilings(MRJob):
    '''
    Legacy only
    '''

    INPUT_PROTOCOL = JSONProtocol
    OUTPUT_PROTOCOL = JSONProtocol


    def mapper(self, fn, data):
        raw_score, tokens, pos_terms, terms = compute_score(data.get('doc'))
        score = (raw_score * pos_terms) / (tokens / 2)
        if score <= 0:
            return
        an = AN_EXTRACT.findall(data.get('header'))
        if len(an) != 1:
            return
        an = an.pop()
        man = an.replace('-', '')
        sic = SIC_EXTRACT.findall(data.get('header')).pop()
        cik = CIK_EXTRACT.findall(data.get('header')).pop()
        url = URL % (int(cik), man, an)
        doc_url = None
        fnames = FILENAME_EXTRACT.findall(data.get('doc'))
        if len(fnames):
            doc_url = fnames.pop()
        if doc_url is not None and len(doc_url.strip()):
            doc_url = urljoin(url, doc_url)
        yield url, {
            #'number': an,
            #'cik': cik,
            'sic': sic,
            'filing_type': TYPE_EXTRACT.findall(data.get('header')).pop(),
            'doc_type': TYPE_EXTRACT.findall(data.get('doc')).pop(),
            'doc_url': doc_url,
            'name': CN_EXTRACT.findall(data.get('header')).pop(),
            'raw_score': raw_score,
            'tokens': tokens,
            'score': score,
            'positive_terms': pos_terms,
            'terms': terms
        }

    def reducer(self, url, files):
        max_score, file_data = 0, None
        for data in files:
            if data.get('score', 0) > max_score:
                max_score = data.get('score', 0)
                file_data = data
        if file_data is not None:
             yield url, file_data


if __name__ == '__main__':
    #parser = argparse.ArgumentParser()
    #parser.add_argument("--stopwords", default="stopwords.txt", help="file containing stopwords")
    #parser.add_argument("--watershed", default="watershed_list.txt", help="file containing watershed file")
    #ARGS = parser.parse_args()
    #class ARGS:
    #    stopwords = os.path.join(os.path.dirname(__file__), 'stopwords.txt')
    #    stopwords = '/tmp/stopwords.txt'
    #    watershed = '/tmp/watershed.txt'

    #STOPWORDS = set(open(ARGS.stopwords).read().lower().split())
    #SEARCHES = makesearchregex(ARGS.watershed)
    #MRScoreFilings.run()
    #MRScoreFiles.run()
    MRScoreFiles.run()
