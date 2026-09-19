"""Local hybrid retrieval over an explicit, versioned documentation allowlist.

BM25 provides exact terminology; character TF-IDF tolerates spelling variants.
Chunks keep stable source/line citations. User prose is never indexed as policy.
"""
import hashlib
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[3] / 'docs'
FILES = ('early-warning.md', 'optimisation-engine.md', 'responsible-recommendations.md',
         'rolling-plans.md', 'predictive-intelligence.md', 'historical-replay.md',
         'watsonx-integration.md', 'port-operations-copilot.md', 'data-lab.md', 'bob-mcp.md')
STOP = set('a an the is are was were of to for how what why do does can i we it in on and or with this that my your me about explain'.split())
ALIASES = {'berthing':'berth', 'cranes':'crane', 'uncertainty':'confidence', 'hallucination':'evidence',
           'accuracy':'evaluation', 'rag':'retrieval', 'uploads':'upload'}


def tokens(text):
    return [ALIASES.get(t, t) for t in re.findall(r'[a-z0-9]+', text.lower()) if len(t)>1 and t not in STOP]


@lru_cache(maxsize=4)
def index(signature):
    chunks = []
    for filename, _, _ in signature:
        lines = (ROOT / filename).read_text(encoding='utf-8').splitlines()
        title, buffer, start, fenced = filename, [], 1, False
        def flush():
            if buffer:
                text = ' '.join(buffer)
                digest = hashlib.sha256(f'{filename}:{start}:{text}'.encode()).hexdigest()[:12]
                chunks.append(dict(id=digest, source='docs/'+filename, title=title, line=start, excerpt=text))
        for number, line in enumerate(lines, 1):
            if line.startswith('```'):
                fenced = not fenced
                continue
            if fenced:
                continue
            if line.startswith('#'):
                flush(); buffer=[]; title=line.lstrip('# ').strip()
            elif line.strip():
                if not buffer: start=number
                buffer.append(line.strip())
                if sum(map(len, buffer)) >= 800:
                    flush(); buffer=[]
            elif buffer:
                flush(); buffer=[]
        flush()
    if not chunks: return chunks, [], {}, 1, None, None
    counts = [Counter(tokens(c['title']+' '+c['excerpt'])) for c in chunks]
    df = Counter(t for row in counts for t in row)
    avg = sum(sum(c.values()) for c in counts)/len(counts)
    vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3,5), max_features=18000)
    matrix = vectorizer.fit_transform([c['title']+' '+c['excerpt'] for c in chunks])
    return chunks, counts, df, avg, vectorizer, matrix


def search(question: str, limit: int = 4):
    signature = tuple((f, (ROOT/f).stat().st_mtime_ns, (ROOT/f).stat().st_size) for f in FILES if (ROOT/f).is_file())
    chunks, counts, df, avg, vectorizer, matrix = index(signature)
    terms = set(tokens(question))
    if not chunks or not terms: return []
    similarities = (matrix @ vectorizer.transform([question]).T).toarray().ravel()
    scored = []
    for i, row in enumerate(counts):
        overlap = terms.intersection(row)
        if not overlap or (len(terms) > 2 and len(overlap)/len(terms) < .2): continue
        bm25 = sum(math.log(1+(len(chunks)-df[t]+.5)/(df[t]+.5))*row[t]*2.5 /
                   (row[t]+1.5*(.25+.75*sum(row.values())/avg)) for t in overlap)
        score = bm25 + 3*float(similarities[i])
        scored.append((score, i))
    ranked = sorted(scored, key=lambda item: (-item[0], chunks[item[1]]['id']))
    result, per_source = [], Counter()
    for score, i in ranked:
        source = chunks[i]['source']
        if per_source[source] >= 2: continue
        result.append(dict(chunks[i], score=round(score, 4)))
        per_source[source] += 1
        if len(result) >= max(1, min(limit, 8)): break
    return result
