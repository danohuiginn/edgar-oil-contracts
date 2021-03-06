'''
pull text from a PDF file
'''
import codecs
import subprocess
import tempfile
import logging
import os
import sha
import functools
try:
    import yapot
except Exception:
    pass

# store copies of our extracted pdfs
cachedir = '/data/_pdftext_cache'

class cached(object):

    def __init__(self, func):
        self.func = func

    def __call__(self, origfn):
        hexdigest = sha.sha(origfn).hexdigest()
        dirname = '%s/%s' % (cachedir, hexdigest[:2])
        cachefn = '%s/%s' % (dirname, hexdigest[2:])
        if os.path.exists(cachefn):
            result = open(cachefn).read()
            return result
        else:
            if not os.path.exists(dirname):
                os.makedirs(dirname)
            result = self.func(origfn)
            with codecs.open(cachefn, 'w', 'utf-8') as fh:
                fh.write(result)
        return result
            

def ocr(fn):
    success, text = yapot.convert_document(fn)
    if success:
        return text
    else:
        return ''

@cached
def pdf2text(fn):
    try:
        bytestr = subprocess.check_output(['pdftotext', fn, '-'])
        text =  bytestr.decode('utf-8', errors='ignore')
    except subprocess.CalledProcessError:
        logging.error('pdf processing error on %s' % fn)
        text =  u''
    #if not text.strip():
    #    text = ocr(fn).decode('utf-8', errors='ignore')
    return text

def pdfdata2txt(data):
    '''
    for when we have data rather than a file
    extract pdf to tempfile, then run pdf2text over it
    '''
    temp = tempfile.NamedTemporaryFile()
    try:
        temp.write(data)
        temp.flush()
        extracted = pdf2text(temp.name)
    finally:
        temp.close()
    return extracted
