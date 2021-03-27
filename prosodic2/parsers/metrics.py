from ..imports import *



#####
# Loading texts
#####
from ..imports import *

# loading txt/strings
def to_txt(txt_or_fn):
    # load txt
    if not txt_or_fn: return
    if os.path.exists(txt_or_fn):
        with open(txt_or_fn) as f:
            txt=f.read()
    else:
        txt=txt_or_fn
    return txt

# tokenizers

# txt -> stanzas
def to_stanzas(full_txt):
    return [st.strip() for st in full_txt.strip().split('\n\n') if st.strip()]

# stanza -> line 
def to_lines(stanza_txt):
    return [l.strip() for l in stanza_txt.split('\n') if l.strip()]

# line -> words
def to_words(line_txt,lang_code=DEFAULT_LANG):
    lang = to_lang(lang_code)
    return lang.tokenize(line_txt)

# word -> sylls
def to_syllables(word_txt,lang_code=DEFAULT_LANG):
    return lang.syllabify(word_txt)



def load(txt_or_fn,lang=DEFAULT_LANG,progress=True,incl_alt=INCL_ALT,num_proc=DEFAULT_NUM_PROC,**kwargs):
    full_txt=to_txt(txt_or_fn)
    if not full_txt: return

    df=pd.DataFrame()
    objs=[]

    for stanza_i,stanza_txt in enumerate(to_stanzas(full_txt)):
        for line_i,line_txt in enumerate(to_lines(stanza_txt)):
            df=line2df(line_txt,lang=lang,incl_alt=incl_alt,**kwargs)
            df['stanza_i']=stanza_i
            df['line_i']=line_i
            df['line_str']=line_txt
            df['line_ipa']=' '.join(df.query('word_ipa!="" & word_ipa_i==0 & syll_i==0').word_ipa)
            df['line_ii']=list(range(len(df)))
            df['num_syll']=len(df.query('word_ipa!="" & word_ipa_i==0'))
            objs+=[df]
    odf=pd.concat(objs)
    assign_proms(odf)
    
    # add other info
    return setindex(odf)
    
def assign_proms(df):
    # set proms
    df['prom_stress']=pd.to_numeric(df['syll_ipa'].apply(getstress),errors='coerce')
    df['prom_strength']=[
        x
        for i,df_word in df.groupby(['word_i','word_ipa_i'])
        for x in getstrength(df_word)
    ]
    df['is_stressed']=(df['prom_stress']>0).apply(np.int32)
    df['is_unstressed']=1-df['is_stressed']
    df['is_peak']=(df['prom_strength']==True).apply(np.int32)
    df['is_trough']=(df['prom_strength']==False).apply(np.int32)



"""
ITER LINES
"""


def iter_lines(txtdf):
    for stanza_i,stanzadf in txtdf.groupby('stanza_i'):
        lines=stanzadf.groupby('line_i')
        for line_,linedf in lines:
            yield linedf


def iter_windows(df,window_len=3):
    for linedf in iter_lines(df):
        ldf=linedf.reset_index()
        linedf_nopunc = ldf[ldf.word_ipa!=""]
        linewords=[y for x,y in sorted(linedf_nopunc.groupby('word_i'))]        
        for lwi,lineword_slice in enumerate(slices(linewords,window_len)):
            for wi,word_combo in enumerate(apply_combos(pd.concat(lineword_slice), 'word_i', 'word_ipa_i', combo_key='word_combo_i')):
                word_combo['word_window_i']=lwi
                yield word_combo



"""
ITER PARSES
"""



def is_ok_parse(parse,maxS=2,maxW=2):
    return ('s'*(maxS+1)) not in parse and ('w'*(maxW+1)) not in parse


def possible_parses(window_len,maxS=2,maxW=2):
    poss = list(product(*[('w','s') for n in range(window_len)]))
    poss = [''.join(x) for x in poss]
    poss = [x for x in poss if is_ok_parse(x)]
    poss = [x for x in poss if len(x)==window_len]
    return poss


def iter_poss_parses(df_window):
    df=df_window
    num_sylls = len(df.reset_index().query('word_ipa!=""'))    
    for posi,pparse in enumerate(possible_parses(num_sylls)):
        df['parse_i']=posi
        df['parse_ii']=list(range(len(pparse)))
        df['parse']=pparse
        df['syll_parse']=list(pparse)
        df['is_w']=[np.int(x=='w') for x in pparse]
        df['is_s']=[np.int(x=='s') for x in pparse]
        yield setindex(df)



def parse_group(df,constraints=DEFAULT_CONSTRAINTS):
    dfpc=apply_constraints(df)
    lkeys=[c for c in df.columns if c not in set(dfpc.columns)]
    return df[lkeys].join(dfpc)



def iter_parsed(df):
    iter=iter_poss_parses(df)
    for pi,dfp in enumerate(iter):
        dfpc=parse_group(dfp)
        yield dfpc


def iter_parsed_windows(df):
    for window in iter_windows(df):
        for parsed in iter_parsed(window):
            yield parsed


def get_parsed_windows(txtdf):
    # get all combos
    return pmap_groups(
        iter_parsed_windows,
        txtdf.groupby(['stanza_i','line_i']),
        progress=True,
        num_proc=7,
        desc='Parsing all windows'
    )



"""
Line -> Stanzas
"""


def summarize_by_syll_pos(df_parsed_windows_of_line,num_syll=10000):
    df=df_parsed_windows_of_line
    qcols=['stanza_i','line_i','line_ii','syll_parse']
    dfr=df[[x for x in df.columns if not x in df.index.names]].reset_index()
    icols=[x for x in dfr.columns if x.endswith('_i') or x.endswith('_ii')]
    dfr_i=dfr[set(icols) | set(qcols)]
    dfr_x=dfr[(set(dfr.columns) - set(icols)) | set(qcols)]
    odf_x=dfr_x.groupby(qcols).mean()
    odf_i=dfr_i.groupby(qcols).count()
    odf=odf_x#.join(odf_i)
    return odf.reset_index()



def apply_combos_meter(dfsyll,group1='line_ii',group2='syll_parse',combo_key='line_parse_i',num_syll=None):
    # combo of indices?
    df=dfsyll

    # ok
    combo_opts = [
        [(mtr,mdf.mean()) for mtr,mdf in sorted(df.groupby(group2))]
        for i,grp in sorted(df.groupby(group1))
    ]

    # is valid?
    combos = product(*combo_opts)
    vci=-1
    done=set()
    for ci,combo in enumerate(combos):
        cparse = ''.join(i for i,x in combo)
        cparse=cparse[:num_syll]
        if cparse in done: continue
        if not is_ok_parse(cparse): continue
        vci+=1
        odf=pd.DataFrame(x for i,x in combo)
        odf['parse_i']=vci
        odf['parse']=cparse
        if type(odf)!=pd.DataFrame or not len(odf): continue
        yield odf
        done|={cparse}

def iter_parsed_lines(df_parsed_windows_of_line):
    numsyll=df_parsed_windows_of_line.num_syll.iloc[0]
    dfsyll = summarize_by_syll_pos(df_parsed_windows_of_line,num_syll=numsyll)
    iterr = apply_combos_meter(dfsyll,num_syll=numsyll)
    yield from iterr

def get_parsed_lines(dfpw,summarized=True):
    df=pmap_groups(
        iter_parsed_lines,
        dfpw.groupby(level=['stanza_i','line_i']),
        num_proc=1,
        progress=True
    )
    
    badcols = [c for c in df.columns if c.startswith('word_') or c.startswith('syll_') or c=='line_ii']
    df=df[set(df.columns) - set(badcols)]
    qkey=['stanza_i','line_i','parse_i','parse']
    df=df.groupby(qkey).mean().sort_index()
    df=df.sort_values(['stanza_i','line_i','*total'])
    return df


def get_info_byline(txtdf):
    linedf=txtdf.xs([0,0,0],level=['word_i','word_ipa_i','syll_i'])
    linedf=linedf.reset_index(level=['word_str','word_ipa','syll_str','syll_ipa','line_ii'],drop=True)
    return linedf#.reset_index().set_index(['stanza_i','line_i'])





def parse(txtdf):
    # already loaded, right?
    if type(txtdf)==str: txtdf=load(txtdf)
    # parse windows
    df_parsed_windows = get_parsed_windows(txtdf)
    # put into lines
    dfparsedlines = get_parsed_lines(df_parsed_windows)
    # get info by line and join
    linedf=get_info_byline(txtdf)
    odf=setindex(joindfs(dfparsedlines, linedf))
    return odf.sort_values('*total')

