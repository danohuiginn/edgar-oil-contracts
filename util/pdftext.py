'''
pull text from a PDF file
'''
import subprocess
import tempfile

def pdf2text(fn):
    bytestr = subprocess.check_output(['pdftotext', fn, '-'])
    return bytestr.decode('utf-8', errors='ignore')

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
