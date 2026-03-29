"""
ARTVAL-MA — Validador de Acervo Tecnico Inteligente
Versao 2.0 | CREA-MA | Pipeline de 5 Agentes Especializados
Hackathon CREA-MA 2026
"""

import streamlit as st
import anthropic
import json
import zipfile
import io
import base64
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS PYDANTIC
# ─────────────────────────────────────────────────────────────────────────────

class Atividade(BaseModel):
    descricao: str
    quantidade: float
    unidade: str


class DadosART(BaseModel):
    numero: str
    contratante_cnpj: str
    contratante_razao_social: str
    contrato_numero: str
    data_inicio: str
    data_termino_previsto: str
    data_solicitacao_baixa: Optional[str] = None
    data_registro_art: Optional[str] = None
    valor_contrato: Optional[float] = None
    atividades: list[Atividade] = Field(default_factory=list)


class DadosAtestado(BaseModel):
    emitente_cnpj: str
    emitente_razao_social: str
    contrato_numero: str
    art_referenciada: str
    data_inicio_periodo: str
    data_termino_periodo: str
    data_emissao: str
    atividades: list[Atividade] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassificacaoDocumento:
    tipo_art: str = ""            # SITAC_PADRAO | ART_LIVRE | DESCONHECIDO
    tipo_atestado: str = ""       # PADRAO_CONFEA | MUNICIPAL | LIVRE
    qualidade_art: str = ""       # ALTO | MEDIO | BAIXO
    qualidade_atestado: str = ""
    estrategia_extracao: str = ""
    observacoes: str = ""


@dataclass
class ReferenciaNormativa:
    id_verificacao: str
    resolucao: str
    artigo: str
    ementa: str
    consequencia: str


@dataclass
class VerificacaoAuditoria:
    id: str
    regra: str
    status: str
    criticidade: str
    detalhe: str
    valor_encontrado: str = ""
    valor_esperado: str = ""
    origem: str = "IA"            # DETERMINISTICO | IA


@dataclass
class ParecerTecnico:
    numero: str
    data_emissao: str
    objeto: str
    sintese_documental: str
    analise_tecnica: str
    conclusao: str
    recomendacao: str
    classificacao_final: str


@dataclass
class RelatorioAuditoria:
    resultado_global: str
    apto_para_cat: bool
    classificacao: Optional[ClassificacaoDocumento] = None
    verificacoes: list[VerificacaoAuditoria] = field(default_factory=list)
    erros_criticos: list[str] = field(default_factory=list)
    referencias_normativas: list[ReferenciaNormativa] = field(default_factory=list)
    parecer: Optional[ParecerTecnico] = None
    recomendacao_final: str = ""
    gerado_em: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA DETERMINISTICA — V03 e V04 (Python puro, sem IA)
# ─────────────────────────────────────────────────────────────────────────────

class DeterministicValidator:
    """
    Valida regras criticas de data de forma deterministica.
    Resultados sao definitivos e sobrescrevem qualquer output da IA.
    """
    DATE_FMT = "%d/%m/%Y"

    def __init__(self, art: dict, atestado: dict) -> None:
        self._art = art
        self._atestado = atestado
        self._resultados: list[VerificacaoAuditoria] = []

    def _parse(self, valor: Optional[str]) -> Optional[date]:
        if not valor:
            return None
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(valor.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _fmt(self, d: Optional[date]) -> str:
        return d.strftime(self.DATE_FMT) if d else "ausente"

    def _verificar_v03(self) -> None:
        termino = self._parse(self._atestado.get("data_termino_periodo"))
        baixa = self._parse(self._art.get("data_solicitacao_baixa"))
        if termino is None or baixa is None:
            self._resultados.append(VerificacaoAuditoria(
                id="V03", regra="Termino do Atestado <= Data de Baixa da ART",
                status="ALERTA", criticidade="ALTA",
                valor_encontrado=self._atestado.get("data_termino_periodo", "ausente"),
                valor_esperado=f"<= {self._art.get('data_solicitacao_baixa', 'ausente')}",
                detalhe="Data ausente ou em formato nao reconhecido. Revise os documentos originais.",
                origem="DETERMINISTICO",
            ))
            return
        delta = (termino - baixa).days
        if delta > 0:
            self._resultados.append(VerificacaoAuditoria(
                id="V03", regra="Termino do Atestado <= Data de Baixa da ART",
                status="ERRO_CRITICO", criticidade="CRITICA",
                valor_encontrado=self._fmt(termino),
                valor_esperado=f"<= {self._fmt(baixa)}",
                detalhe=(
                    f"Periodo do Atestado termina {delta} dia(s) apos a baixa da ART "
                    f"({self._fmt(baixa)}). Atestado nao pode cobrir periodo posterior "
                    f"a vigencia da ART. Resolucao CONFEA 1.025/2009, Art. 8."
                ),
                origem="DETERMINISTICO",
            ))
        else:
            self._resultados.append(VerificacaoAuditoria(
                id="V03", regra="Termino do Atestado <= Data de Baixa da ART",
                status="CONFORME", criticidade="CRITICA",
                valor_encontrado=self._fmt(termino),
                valor_esperado=f"<= {self._fmt(baixa)}",
                detalhe=f"Termino do Atestado ({self._fmt(termino)}) anterior ou igual a baixa da ART. Conforme.",
                origem="DETERMINISTICO",
            ))

    def _verificar_v04(self) -> None:
        emissao = self._parse(self._atestado.get("data_emissao"))
        baixa = self._parse(self._art.get("data_solicitacao_baixa"))
        if emissao is None or baixa is None:
            self._resultados.append(VerificacaoAuditoria(
                id="V04", regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="ALERTA", criticidade="CRITICA",
                valor_encontrado=self._atestado.get("data_emissao", "ausente"),
                valor_esperado=f"<= {self._art.get('data_solicitacao_baixa', 'ausente')}",
                detalhe="Data ausente. ATENCAO: diferenca de +1 dia ja causa indeferimento no SITAC.",
                origem="DETERMINISTICO",
            ))
            return
        delta = (emissao - baixa).days
        if delta > 0:
            self._resultados.append(VerificacaoAuditoria(
                id="V04", regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="ERRO_CRITICO", criticidade="CRITICA",
                valor_encontrado=self._fmt(emissao),
                valor_esperado=f"<= {self._fmt(baixa)}",
                detalhe=(
                    f"Atestado emitido {delta} dia(s) apos a baixa da ART ({self._fmt(baixa)}). "
                    f"Pelo padrao SITAC/MA, +1 dia ja configura indeferimento imediato. "
                    f"Resolucao CONFEA 1.025/2009, Art. 8."
                ),
                origem="DETERMINISTICO",
            ))
        else:
            self._resultados.append(VerificacaoAuditoria(
                id="V04", regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="CONFORME", criticidade="CRITICA",
                valor_encontrado=self._fmt(emissao),
                valor_esperado=f"<= {self._fmt(baixa)}",
                detalhe=f"Emissao ({self._fmt(emissao)}) anterior ou igual a baixa da ART. Conforme.",
                origem="DETERMINISTICO",
            ))

    def executar(self) -> list[VerificacaoAuditoria]:
        self._resultados = []
        self._verificar_v03()
        self._verificar_v04()
        return self._resultados

    def tem_erro_critico(self) -> bool:
        return any(v.status == "ERRO_CRITICO" for v in self._resultados)

    def serializar_para_prompt(self) -> str:
        linhas = ["PRE-VALIDACAO DETERMINISTICA (nao pode ser contradita):"]
        for v in self._resultados:
            linhas.append(
                f"  [{v.id}] {v.status} | encontrado={v.valor_encontrado} | esperado={v.valor_esperado}"
            )
        return "\n".join(linhas)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def extrair_texto_de_upload(uploaded_file) -> tuple[str, bytes]:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    raw = uploaded_file.read()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            texto, imagem_bytes = "", b""
            for name in z.namelist():
                low = name.lower()
                if low.endswith(".txt"):
                    rb = z.read(name)
                    try:
                        texto = rb.decode("utf-8")
                    except UnicodeDecodeError:
                        texto = rb.decode("latin-1", errors="replace")
                if low.endswith((".jpeg", ".jpg", ".png")):
                    imagem_bytes = z.read(name)
            if texto.strip():
                return texto.strip(), imagem_bytes
            if imagem_bytes:
                return "", imagem_bytes
    except Exception:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        texto = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if texto:
            return texto, b""
    except Exception:
        pass
    return "", raw


def bytes_para_base64(b: bytes) -> str:
    return base64.standard_b64encode(b).decode("utf-8")


def ocr_via_claude(imagem_bytes: bytes, tipo_doc: str, client: anthropic.Anthropic) -> str:
    try:
        b64 = bytes_para_base64(imagem_bytes)
        mime = "image/png" if imagem_bytes[:8] == b'\x89PNG\r\n\x1a\n' else "image/jpeg"
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": (
                    f"Documento {tipo_doc} SITAC/CREA-MA. "
                    "Transcreva todo o texto visivel preservando labels e valores. Apenas o texto."
                )},
            ]}],
        )
        return resp.content[0].text
    except Exception:
        return ""


def _chamar_claude(prompt: str, client: anthropic.Anthropic, max_tokens: int = 4096) -> str:
    return client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ).content[0].text


def _json(texto: str) -> dict:
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = "\n".join(limpo.splitlines()[1:-1])
    return json.loads(limpo)


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

CNPJ_ESPERADO = "36.408.654/0001-04"

P_CLASSIFICACAO = """
Voce e um classificador de documentos tecnicos do sistema SITAC/CREA-MA.
Analise os textos e retorne SOMENTE JSON valido, sem markdown.

TEXTO ART:
{texto_art}

TEXTO ATESTADO:
{texto_atestado}

Retorne exatamente:
{{
  "tipo_art": "SITAC_PADRAO | ART_LIVRE | DESCONHECIDO",
  "tipo_atestado": "PADRAO_CONFEA | MUNICIPAL | LIVRE",
  "qualidade_art": "ALTO | MEDIO | BAIXO",
  "qualidade_atestado": "ALTO | MEDIO | BAIXO",
  "estrategia_extracao": "frase curta sobre como extrair melhor estes documentos",
  "observacoes": "alertas relevantes sobre formato ou conteudo"
}}
"""

P_EXTRACAO = """
Voce e um extrator especialista em documentos SITAC/CREA-MA.
Tipo da ART: {tipo_art} | Tipo do Atestado: {tipo_atestado}
Estrategia: {estrategia}

TEXTO ART:
{texto_art}

TEXTO ATESTADO:
{texto_atestado}

Retorne SOMENTE JSON valido, sem markdown:
{{
  "art": {{
    "numero": "",
    "contratante_cnpj": "",
    "contratante_razao_social": "",
    "contrato_numero": "",
    "data_inicio": "",
    "data_termino_previsto": "",
    "data_solicitacao_baixa": "",
    "data_registro_art": "",
    "valor_contrato": 0.0,
    "atividades": [{{"descricao": "", "quantidade": 0.0, "unidade": ""}}]
  }},
  "atestado": {{
    "emitente_cnpj": "",
    "emitente_razao_social": "",
    "contrato_numero": "",
    "art_referenciada": "",
    "data_inicio_periodo": "",
    "data_termino_periodo": "",
    "data_emissao": "",
    "atividades": [{{"descricao": "", "quantidade": 0.0, "unidade": ""}}]
  }}
}}
Regras: datas em DD/MM/AAAA. data_solicitacao_baixa = campo "Data da Solicitacao" na secao Baixa da ART.
"""

P_AUDITORIA = """
Voce e um auditor tecnico especialista nas normas SITAC/MA do CREA-MA.
CNPJ obrigatorio: {cnpj_esperado}

DADOS EXTRAIDOS:
{dados_json}

{validacao_deterministica}

Execute SOMENTE V01, V02, V05, V06, V07. Reproduza V03 e V04 exatamente como indicado acima.

REGRAS:
V01 — CNPJ da ART == {cnpj_esperado}
V02 — CNPJ do Atestado == {cnpj_esperado}
V05 — Atividades coincidem em descricao e quantidade (tolerancia zero)
V06 — Numero do contrato identico em ART e Atestado
V07 — Numero da ART referenciada no Atestado == numero da ART

Retorne SOMENTE JSON valido, sem markdown:
{{
  "resultado_global": "APROVADO | APROVADO COM OBSERVACAO | REPROVADO",
  "apto_para_cat": true | false,
  "verificacoes": [
    {{
      "id": "V01",
      "regra": "descricao curta",
      "status": "CONFORME | ERRO_CRITICO | ALERTA",
      "criticidade": "CRITICA | ALTA | MEDIA",
      "valor_encontrado": "",
      "valor_esperado": "",
      "detalhe": "explicacao tecnica"
    }}
  ],
  "erros_criticos": ["V01"],
  "recomendacao_final": "orientacao objetiva de proximos passos"
}}
"""

P_CONSULTORIA = """
Voce e um consultor juridico-normativo especialista em resolucoes CONFEA/CREA.
Para cada erro ou alerta, cite a fundamentacao normativa exata.

VERIFICACOES COM PROBLEMAS:
{verificacoes_json}

Retorne SOMENTE JSON valido, sem markdown:
{{
  "referencias": [
    {{
      "id_verificacao": "V01",
      "resolucao": "Resolucao CONFEA 1.025/2009",
      "artigo": "Art. 8, paragrafo 2",
      "ementa": "descricao resumida do que o artigo determina",
      "consequencia": "o que acontece se a irregularidade nao for sanada"
    }}
  ]
}}
Se nao houver erros: {{"referencias": []}}
"""

P_PARECER = """
Voce e um engenheiro auditor senior do CREA-MA emitindo parecer tecnico formal.
Redija em linguagem formal PT-BR, pronto para protocolo.

RESULTADO DA AUDITORIA:
{auditoria_json}

Retorne SOMENTE JSON valido, sem markdown:
{{
  "numero": "PAR-{ano}-{seq}",
  "data_emissao": "{data_hoje}",
  "objeto": "frase objetiva sobre o que foi auditado",
  "sintese_documental": "2-3 paragrafos descrevendo os documentos, caracteristicas e campos-chave",
  "analise_tecnica": "2-3 paragrafos com analise de cada verificacao relevante, citando normas",
  "conclusao": "1 paragrafo conclusivo sobre conformidade ou nao conformidade",
  "recomendacao": "orientacao especifica e acionavel",
  "classificacao_final": "APTO PARA EMISSAO DE CAT | INAPTO — REQUER CORRECOES | INAPTO — INDEFERIMENTO PREVISTO"
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# AGENTES
# ─────────────────────────────────────────────────────────────────────────────

def agent1_classificar(
    texto_art: str,
    texto_atestado: str,
    client: anthropic.Anthropic,
) -> ClassificacaoDocumento:
    """Agente 1 — Identifica tipo, qualidade e estrategia de extracao dos documentos."""
    try:
        dados = _json(_chamar_claude(
            P_CLASSIFICACAO.format(texto_art=texto_art[:3000], texto_atestado=texto_atestado[:3000]),
            client, max_tokens=1024,
        ))
        return ClassificacaoDocumento(
            tipo_art=dados.get("tipo_art", "DESCONHECIDO"),
            tipo_atestado=dados.get("tipo_atestado", "LIVRE"),
            qualidade_art=dados.get("qualidade_art", "MEDIO"),
            qualidade_atestado=dados.get("qualidade_atestado", "MEDIO"),
            estrategia_extracao=dados.get("estrategia_extracao", "Extracao padrao"),
            observacoes=dados.get("observacoes", ""),
        )
    except Exception:
        return ClassificacaoDocumento(
            tipo_art="DESCONHECIDO", tipo_atestado="LIVRE",
            qualidade_art="MEDIO", qualidade_atestado="MEDIO",
            estrategia_extracao="Extracao padrao",
            observacoes="Classificacao automatica falhou — usando configuracao default.",
        )


def agent2_extrair(
    texto_art: str,
    texto_atestado: str,
    classificacao: ClassificacaoDocumento,
    client: anthropic.Anthropic,
) -> tuple[dict, dict]:
    """Agente 2 — Extrai dados estruturados com base na classificacao do Agente 1."""
    dados = _json(_chamar_claude(
        P_EXTRACAO.format(
            tipo_art=classificacao.tipo_art,
            tipo_atestado=classificacao.tipo_atestado,
            estrategia=classificacao.estrategia_extracao,
            texto_art=texto_art,
            texto_atestado=texto_atestado,
        ),
        client,
    ))
    return dados.get("art", {}), dados.get("atestado", {})


def agent3_auditar(
    art_dict: dict,
    atestado_dict: dict,
    resultados_det: list[VerificacaoAuditoria],
    validator: DeterministicValidator,
    client: anthropic.Anthropic,
) -> tuple[list[VerificacaoAuditoria], list[str], str, str]:
    """Agente 3 — Audita V01/V02/V05-V07 e consolida com camada deterministica."""
    dados = {"art": art_dict, "atestado": atestado_dict}
    resultado = _json(_chamar_claude(
        P_AUDITORIA.format(
            cnpj_esperado=CNPJ_ESPERADO,
            dados_json=json.dumps(dados, ensure_ascii=False, indent=2),
            validacao_deterministica=validator.serializar_para_prompt(),
        ),
        client,
    ))

    # Substitui V03/V04 pelos resultados deterministicos
    det_por_id = {v.id: v for v in resultados_det}
    verificacoes_raw = resultado.get("verificacoes", [])
    ids_presentes = {v.get("id") for v in verificacoes_raw}
    finais: list[VerificacaoAuditoria] = []

    for v in verificacoes_raw:
        vid = v.get("id", "")
        if vid in det_por_id:
            d = det_por_id[vid]
            finais.append(VerificacaoAuditoria(
                id=d.id, regra=d.regra, status=d.status, criticidade=d.criticidade,
                detalhe=d.detalhe, valor_encontrado=d.valor_encontrado,
                valor_esperado=d.valor_esperado, origem="DETERMINISTICO",
            ))
        else:
            finais.append(VerificacaoAuditoria(
                id=vid, regra=v.get("regra", ""), status=v.get("status", ""),
                criticidade=v.get("criticidade", ""), detalhe=v.get("detalhe", ""),
                valor_encontrado=v.get("valor_encontrado", ""),
                valor_esperado=v.get("valor_esperado", ""), origem="IA",
            ))

    for vid, det in det_por_id.items():
        if vid not in ids_presentes:
            finais.append(VerificacaoAuditoria(
                id=det.id, regra=det.regra, status=det.status, criticidade=det.criticidade,
                detalhe=det.detalhe, valor_encontrado=det.valor_encontrado,
                valor_esperado=det.valor_esperado, origem="DETERMINISTICO",
            ))

    finais.sort(key=lambda v: v.id)

    ids_criticos_det = [v.id for v in resultados_det if v.status == "ERRO_CRITICO"]
    ids_criticos_ia = resultado.get("erros_criticos", [])
    erros_criticos = list(dict.fromkeys(
        ids_criticos_det + [e for e in ids_criticos_ia if e not in ids_criticos_det]
    ))

    resultado_global = resultado.get("resultado_global", "REPROVADO")
    if erros_criticos and resultado_global != "REPROVADO":
        resultado_global = "REPROVADO"

    return finais, erros_criticos, resultado_global, resultado.get("recomendacao_final", "")


def agent4_consultar_normas(
    verificacoes: list[VerificacaoAuditoria],
    client: anthropic.Anthropic,
) -> list[ReferenciaNormativa]:
    """Agente 4 — Cita resolucoes CONFEA/CREA para cada erro ou alerta."""
    problemas = [v for v in verificacoes if v.status in ("ERRO_CRITICO", "ALERTA")]
    if not problemas:
        return []
    try:
        dados = _json(_chamar_claude(
            P_CONSULTORIA.format(verificacoes_json=json.dumps(
                [{"id": v.id, "regra": v.regra, "status": v.status, "detalhe": v.detalhe}
                 for v in problemas],
                ensure_ascii=False, indent=2,
            )),
            client, max_tokens=2048,
        ))
        return [
            ReferenciaNormativa(
                id_verificacao=r.get("id_verificacao", ""),
                resolucao=r.get("resolucao", ""),
                artigo=r.get("artigo", ""),
                ementa=r.get("ementa", ""),
                consequencia=r.get("consequencia", ""),
            )
            for r in dados.get("referencias", [])
        ]
    except Exception:
        return []


def agent5_redigir_parecer(
    art_dict: dict,
    atestado_dict: dict,
    verificacoes: list[VerificacaoAuditoria],
    referencias: list[ReferenciaNormativa],
    resultado_global: str,
    apto_cat: bool,
    recomendacao_final: str,
    client: anthropic.Anthropic,
) -> Optional[ParecerTecnico]:
    """Agente 5 — Redige parecer tecnico formal pronto para protocolo no CREA-MA."""
    auditoria = {
        "resultado_global": resultado_global,
        "apto_para_cat": apto_cat,
        "art": art_dict,
        "atestado": atestado_dict,
        "verificacoes": [
            {"id": v.id, "regra": v.regra, "status": v.status,
             "detalhe": v.detalhe, "valor_encontrado": v.valor_encontrado}
            for v in verificacoes
        ],
        "referencias_normativas": [
            {"id": r.id_verificacao, "resolucao": r.resolucao,
             "artigo": r.artigo, "ementa": r.ementa, "consequencia": r.consequencia}
            for r in referencias
        ],
        "recomendacao_final": recomendacao_final,
    }
    try:
        dados = _json(_chamar_claude(
            P_PARECER.format(
                auditoria_json=json.dumps(auditoria, ensure_ascii=False, indent=2),
                ano=datetime.now().year,
                seq=datetime.now().strftime("%m%d%H%M"),
                data_hoje=datetime.now().strftime("%d/%m/%Y"),
            ),
            client, max_tokens=3000,
        ))
        return ParecerTecnico(
            numero=dados.get("numero", ""),
            data_emissao=dados.get("data_emissao", datetime.now().strftime("%d/%m/%Y")),
            objeto=dados.get("objeto", ""),
            sintese_documental=dados.get("sintese_documental", ""),
            analise_tecnica=dados.get("analise_tecnica", ""),
            conclusao=dados.get("conclusao", ""),
            recomendacao=dados.get("recomendacao", ""),
            classificacao_final=dados.get("classificacao_final", ""),
        )
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ORQUESTRADOR
# ─────────────────────────────────────────────────────────────────────────────

def executar_pipeline(
    texto_art: str,
    texto_atestado: str,
    client: anthropic.Anthropic,
    container,
) -> tuple[dict, dict, RelatorioAuditoria]:

    with container.status("Agente 1 — Classificador de Documentos", expanded=True) as s:
        classificacao = agent1_classificar(texto_art, texto_atestado, client)
        s.update(
            label=(
                f"Agente 1 — ART: {classificacao.tipo_art} ({classificacao.qualidade_art}) "
                f"| Atestado: {classificacao.tipo_atestado} ({classificacao.qualidade_atestado})"
            ),
            state="complete",
        )

    with container.status("Agente 2 — Extrator Estruturado", expanded=True) as s:
        try:
            art_dict, atestado_dict = agent2_extrair(
                texto_art, texto_atestado, classificacao, client
            )
            s.update(
                label=(
                    f"Agente 2 — ART {art_dict.get('numero', '?')} "
                    f"| Contrato {art_dict.get('contrato_numero', '?')}"
                ),
                state="complete",
            )
        except Exception as e:
            s.update(label=f"Agente 2 falhou: {e}", state="error")
            raise

    with container.status("Camada Deterministica — V03/V04", expanded=True) as s:
        validator = DeterministicValidator(art_dict, atestado_dict)
        resultados_det = validator.executar()
        ids_det = [v.id for v in resultados_det if v.status == "ERRO_CRITICO"]
        s.update(
            label=(
                f"Deterministica — {len(ids_det)} erro(s) critico(s): {', '.join(ids_det)}"
                if ids_det else "Deterministica — V03/V04 conformes"
            ),
            state="error" if ids_det else "complete",
        )

    with container.status("Agente 3 — Auditor SITAC/MA (V01/V02/V05-V07)", expanded=True) as s:
        try:
            verificacoes, erros_criticos, resultado_global, recomendacao = agent3_auditar(
                art_dict, atestado_dict, resultados_det, validator, client
            )
            s.update(
                label=f"Agente 3 — {resultado_global} | {len(erros_criticos)} erro(s) critico(s)",
                state="error" if erros_criticos else "complete",
            )
        except Exception as e:
            s.update(label=f"Agente 3 falhou: {e}", state="error")
            raise

    with container.status("Agente 4 — Consultor Normativo CONFEA/CREA", expanded=True) as s:
        referencias = agent4_consultar_normas(verificacoes, client)
        s.update(
            label=f"Agente 4 — {len(referencias)} referencia(s) normativa(s) citada(s)",
            state="complete",
        )

    apto_cat = len(erros_criticos) == 0
    with container.status("Agente 5 — Redator de Parecer Tecnico", expanded=True) as s:
        parecer = agent5_redigir_parecer(
            art_dict, atestado_dict, verificacoes, referencias,
            resultado_global, apto_cat, recomendacao, client,
        )
        s.update(
            label=f"Agente 5 — Parecer {parecer.numero if parecer else 'N/A'} emitido",
            state="complete",
        )

    relatorio = RelatorioAuditoria(
        resultado_global=resultado_global,
        apto_para_cat=apto_cat,
        classificacao=classificacao,
        verificacoes=verificacoes,
        erros_criticos=erros_criticos,
        referencias_normativas=referencias,
        parecer=parecer,
        recomendacao_final=recomendacao,
    )
    return art_dict, atestado_dict, relatorio


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def formatar_parecer_txt(p: ParecerTecnico) -> str:
    sep = "─" * 72
    return f"""{sep}
CONSELHO REGIONAL DE ENGENHARIA E AGRONOMIA DO MARANHAO — CREA-MA
SISTEMA DE INFORMACOES TECNICAS DO ACERVO DE CAPACIDADE TECNICA — SITAC

PARECER TECNICO N. {p.numero}
Data de Emissao: {p.data_emissao}
{sep}

OBJETO
{p.objeto}

{sep}
SINTESE DOCUMENTAL
{p.sintese_documental}

{sep}
ANALISE TECNICA
{p.analise_tecnica}

{sep}
CONCLUSAO
{p.conclusao}

{sep}
RECOMENDACAO
{p.recomendacao}

{sep}
CLASSIFICACAO FINAL: {p.classificacao_final}
{sep}

Documento gerado automaticamente pelo sistema ARTVAL-MA v2.0
CREA-MA | Hackathon 2026""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');
*, html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.block-container { padding-top: 2rem; padding-bottom: 4rem; max-width: 1100px; }

.sitac-header { background: #0a1628; border: 1px solid #1c3350; border-radius: 12px; padding: 2.4rem 2.4rem 2rem; margin-bottom: 2rem; position: relative; overflow: hidden; }
.sitac-header::after { content: ""; position: absolute; right: 0; top: 0; bottom: 0; width: 280px; background: linear-gradient(90deg, transparent, rgba(14,60,110,0.4)); pointer-events: none; }
.sitac-badge { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 500; letter-spacing: 0.1em; text-transform: uppercase; color: #4a9bbe; border: 1px solid #1c3a55; background: rgba(74,155,190,0.08); padding: 3px 12px; border-radius: 3px; margin-bottom: 1rem; }
.sitac-header h1 { color: #ddeef8; font-size: 1.65rem; font-weight: 600; margin: 0 0 0.4rem 0; letter-spacing: -0.02em; }
.sitac-header p { color: #5a85a5; font-size: 0.82rem; font-family: 'IBM Plex Mono', monospace; margin: 0; }

.pipeline-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 0; margin-bottom: 0.5rem; border: 1px solid #0f2035; border-radius: 10px; overflow: hidden; }
.agent-cell { padding: 1rem 0.8rem; background: #060f1a; border-right: 1px solid #0f2035; text-align: center; }
.agent-cell:last-child { border-right: none; }
.agent-cell.det { background: #06101c; }
.agent-cell.wide { grid-column: 1 / -1; background: #050d17; border-top: 1px solid #0f2035; }
.agent-num { font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; letter-spacing: 0.12em; text-transform: uppercase; color: #2a4a62; margin-bottom: 0.4rem; }
.agent-icon { font-size: 1.1rem; margin-bottom: 0.35rem; }
.agent-name { font-size: 0.75rem; font-weight: 600; color: #6a90a8; line-height: 1.3; }
.agent-sub { font-size: 0.62rem; font-family: 'IBM Plex Mono', monospace; color: #1a3a52; margin-top: 0.25rem; }

.upload-label { background: #0c1c30; border: 1px solid #1c3350; border-radius: 8px; padding: 1.2rem 1.4rem; margin-bottom: 0.6rem; }
.doc-type { font-size: 0.65rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.1em; text-transform: uppercase; color: #4a7a9a; margin-bottom: 0.3rem; }
.doc-title { font-size: 0.95rem; font-weight: 600; color: #b8d4e8; margin-bottom: 0.15rem; }
.doc-hint { font-size: 0.75rem; color: #3a5a72; font-family: 'IBM Plex Mono', monospace; }
div[data-testid="stFileUploadDropzone"] { background: #081422 !important; border: 1px dashed #1c3350 !important; border-radius: 6px !important; }

.result-banner { border-radius: 8px; padding: 1.5rem 2rem; margin-bottom: 1.8rem; display: flex; align-items: center; gap: 1.4rem; }
.result-banner.aprovado { background: #071a0f; border: 1px solid #1a4a28; }
.result-banner.reprovado { background: #180808; border: 1px solid #4a1a1a; }
.result-banner.aviso { background: #16110a; border: 1px solid #4a3a10; }
.status-indicator { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.aprovado .status-indicator { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,0.4); }
.reprovado .status-indicator { background: #ef4444; box-shadow: 0 0 8px rgba(239,68,68,0.4); }
.aviso .status-indicator { background: #f59e0b; box-shadow: 0 0 8px rgba(245,158,11,0.4); }
.status-title { font-size: 1rem; font-weight: 600; letter-spacing: 0.03em; margin-bottom: 0.2rem; }
.aprovado .status-title { color: #4ade80; }
.reprovado .status-title { color: #f87171; }
.aviso .status-title { color: #fbbf24; }
.status-sub { font-size: 0.78rem; font-family: 'IBM Plex Mono', monospace; }
.aprovado .status-sub { color: #2a5a3a; }
.reprovado .status-sub { color: #5a2a2a; }
.aviso .status-sub { color: #5a4a1a; }

.classif-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.8rem; margin-bottom: 0.5rem; }
.classif-cell { background: #081422; border: 1px solid #0f2035; border-radius: 6px; padding: 0.8rem 1rem; }
.classif-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase; color: #2a4a62; margin-bottom: 0.3rem; }
.classif-val { font-size: 0.82rem; font-weight: 500; color: #7aaec8; }
.classif-obs { font-size: 0.72rem; color: #3a5a72; margin-top: 0.2rem; }

.secao { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: #3a5a72; padding-bottom: 0.6rem; border-bottom: 1px solid #0f2035; margin: 2rem 0 1rem 0; }

.data-block { background: #081422; border: 1px solid #0f2035; border-radius: 8px; padding: 1rem 1.2rem; }
.block-title { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase; color: #3a6a8a; margin-bottom: 0.8rem; padding-bottom: 0.5rem; border-bottom: 1px solid #0f2035; }
.data-row { display: flex; gap: 0.8rem; padding: 0.38rem 0; border-bottom: 1px solid #0a1a28; align-items: baseline; }
.data-row:last-child { border-bottom: none; }
.data-key { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: #3a5a72; min-width: 155px; text-transform: uppercase; letter-spacing: 0.04em; flex-shrink: 0; }
.data-val { font-size: 0.85rem; color: #a8cce0; }

.verif-card { border-radius: 6px; padding: 0.9rem 1.1rem; margin-bottom: 0.6rem; border-left: 3px solid transparent; }
.verif-card.conforme { background: #06120a; border-left-color: #16a34a; }
.verif-card.erro { background: #120606; border-left-color: #dc2626; }
.verif-card.alerta { background: #110d04; border-left-color: #d97706; }
.verif-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; gap: 0.4rem; }
.verif-id { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: #2a4a62; margin-right: 0.6rem; }
.verif-regra { font-size: 0.85rem; font-weight: 500; color: #a8c8e0; }
.verif-badges { display: flex; gap: 0.4rem; align-items: center; flex-shrink: 0; }
.verif-badge { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; font-weight: 600; letter-spacing: 0.08em; padding: 2px 9px; border-radius: 3px; white-space: nowrap; }
.badge-conforme { background: rgba(22,163,74,0.12); color: #4ade80; border: 1px solid rgba(22,163,74,0.25); }
.badge-erro { background: rgba(220,38,38,0.12); color: #f87171; border: 1px solid rgba(220,38,38,0.25); }
.badge-alerta { background: rgba(217,119,6,0.12); color: #fbbf24; border: 1px solid rgba(217,119,6,0.25); }
.badge-det { background: rgba(99,102,241,0.10); color: #818cf8; border: 1px solid rgba(99,102,241,0.2); font-size: 0.55rem; }
.badge-ia { background: rgba(45,90,120,0.10); color: #4a7a9a; border: 1px solid rgba(45,90,120,0.2); font-size: 0.55rem; }
.verif-valores { font-size: 0.76rem; font-family: 'IBM Plex Mono', monospace; color: #2a4a62; margin-bottom: 0.4rem; }
.verif-detalhe { font-size: 0.8rem; color: #6a90a8; line-height: 1.5; }
.verif-card.erro .verif-detalhe { color: #8a5050; }

.norma-card { background: #07101e; border: 1px solid #102030; border-radius: 6px; padding: 0.8rem 1rem; margin-bottom: 0.5rem; display: grid; grid-template-columns: 36px 1fr; gap: 0.5rem 0.8rem; align-items: start; }
.norma-id { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: #818cf8; padding-top: 0.1rem; }
.norma-resolucao { font-size: 0.8rem; font-weight: 600; color: #8ab0cc; margin-bottom: 0.15rem; }
.norma-artigo { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: #3a6080; margin-bottom: 0.2rem; }
.norma-ementa { font-size: 0.78rem; color: #5a8098; margin-bottom: 0.2rem; line-height: 1.4; }
.norma-consequencia { font-size: 0.75rem; color: #7a4040; font-style: italic; }

.parecer-wrapper { background: #07101c; border: 1px solid #1a3450; border-radius: 10px; padding: 2rem 2.4rem; margin-top: 0.5rem; }
.parecer-topo { text-align: center; padding-bottom: 1.5rem; border-bottom: 1px solid #0f2035; margin-bottom: 1.5rem; }
.parecer-orgao { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.12em; text-transform: uppercase; color: #4a7a9a; margin-bottom: 0.4rem; }
.parecer-titulo { font-size: 1rem; font-weight: 700; color: #c8e0f0; letter-spacing: 0.04em; margin-bottom: 0.2rem; }
.parecer-numero { font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: #3a6080; }
.parecer-secao { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: #2a5a78; margin: 1.2rem 0 0.5rem 0; padding-bottom: 0.3rem; border-bottom: 1px solid #0c1c2e; }
.parecer-texto { font-size: 0.85rem; color: #8ab0cc; line-height: 1.7; text-align: justify; }
.parecer-classificacao { text-align: center; margin-top: 1.5rem; padding-top: 1.5rem; border-top: 1px solid #0f2035; }
.classif-tag { display: inline-block; font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.08em; padding: 6px 20px; border-radius: 4px; }
.classif-tag.apto { background: rgba(22,163,74,0.12); color: #4ade80; border: 1px solid rgba(22,163,74,0.3); }
.classif-tag.inapto { background: rgba(220,38,38,0.12); color: #f87171; border: 1px solid rgba(220,38,38,0.3); }
</style>
"""

PIPELINE_HTML = """
<div class="pipeline-grid">
  <div class="agent-cell">
    <div class="agent-num">Agente 01</div>
    <div class="agent-icon">&#x1F50D;</div>
    <div class="agent-name">Classificador</div>
    <div class="agent-sub">Tipo &amp; Qualidade</div>
  </div>
  <div class="agent-cell">
    <div class="agent-num">Agente 02</div>
    <div class="agent-icon">&#x1F4CB;</div>
    <div class="agent-name">Extrator</div>
    <div class="agent-sub">JSON Estruturado</div>
  </div>
  <div class="agent-cell det">
    <div class="agent-num">Camada Python</div>
    <div class="agent-icon">&#x26A1;</div>
    <div class="agent-name">Validador Det.</div>
    <div class="agent-sub">V03 &amp; V04</div>
  </div>
  <div class="agent-cell">
    <div class="agent-num">Agente 03</div>
    <div class="agent-icon">&#x2696;</div>
    <div class="agent-name">Auditor SITAC</div>
    <div class="agent-sub">V01/V02/V05-V07</div>
  </div>
  <div class="agent-cell">
    <div class="agent-num">Agente 04</div>
    <div class="agent-icon">&#x1F4DA;</div>
    <div class="agent-name">Consultor Norm.</div>
    <div class="agent-sub">Resolucoes CONFEA</div>
  </div>
  <div class="agent-cell wide">
    <div class="agent-num">Agente 05</div>
    <div class="agent-icon">&#x1F4DD;</div>
    <div class="agent-name">Redator de Parecer Tecnico — Documento formal pronto para protocolo CREA-MA</div>
  </div>
</div>
"""


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────

def linha_dado(chave: str, valor) -> str:
    return (
        f'<div class="data-row">'
        f'<span class="data-key">{chave}</span>'
        f'<span class="data-val">{valor or "—"}</span>'
        f'</div>'
    )


st.set_page_config(
    page_title="Validador SITAC/MA — CREA-MA",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)

st.markdown("""
<div class="sitac-header">
  <div class="sitac-badge">CREA-MA &nbsp;&middot;&nbsp; Sistema SITAC &nbsp;&middot;&nbsp; v2.0</div>
  <h1>Validador de Acervo Tecnico</h1>
  <p>Pipeline de 5 agentes especializados &nbsp;&middot;&nbsp; Auditoria automatica ART x Atestado para emissao de CAT</p>
</div>
""", unsafe_allow_html=True)

st.markdown('<div class="secao">Pipeline de Analise</div>', unsafe_allow_html=True)
st.markdown(PIPELINE_HTML, unsafe_allow_html=True)

st.markdown('<div class="secao">Documentos</div>', unsafe_allow_html=True)
col1, col2 = st.columns(2, gap="large")

with col1:
    st.markdown("""<div class="upload-label">
      <div class="doc-type">Documento 01</div>
      <div class="doc-title">ART — Anotacao de Responsabilidade Tecnica</div>
      <div class="doc-hint">Exportado do SITAC &nbsp;|&nbsp; .pdf ou .zip</div>
    </div>""", unsafe_allow_html=True)
    upload_art = st.file_uploader("ART", type=["pdf", "zip"], key="art_upload", label_visibility="collapsed")

with col2:
    st.markdown("""<div class="upload-label">
      <div class="doc-type">Documento 02</div>
      <div class="doc-title">Atestado de Capacidade Tecnica</div>
      <div class="doc-hint">Emitido pelo contratante &nbsp;|&nbsp; .pdf ou .zip</div>
    </div>""", unsafe_allow_html=True)
    upload_atestado = st.file_uploader("Atestado", type=["pdf", "zip"], key="atestado_upload", label_visibility="collapsed")

st.divider()
_, col_btn, _ = st.columns([2, 1, 2])
with col_btn:
    btn_validar = st.button(
        "Executar Validacao",
        use_container_width=True,
        type="primary",
        disabled=(upload_art is None or upload_atestado is None),
    )

if upload_art is None or upload_atestado is None:
    st.info("Carregue os dois documentos para iniciar a validacao.")
    st.stop()

if not btn_validar:
    st.stop()

try:
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except KeyError:
    st.error("Chave ANTHROPIC_API_KEY nao configurada. Verifique .streamlit/secrets.toml.")
    st.stop()

client = anthropic.Anthropic(api_key=api_key)

upload_art.seek(0)
upload_atestado.seek(0)
texto_art, img_art = extrair_texto_de_upload(upload_art)
texto_atestado, img_atestado = extrair_texto_de_upload(upload_atestado)

if not texto_art and img_art:
    texto_art = ocr_via_claude(img_art, "ART", client)
if not texto_atestado and img_atestado:
    texto_atestado = ocr_via_claude(img_atestado, "Atestado", client)

if not texto_art or not texto_atestado:
    st.error("Nao foi possivel extrair texto. Use arquivos exportados diretamente do SITAC/MA.")
    st.stop()

st.markdown('<div class="secao">Execucao do Pipeline</div>', unsafe_allow_html=True)

try:
    art_dict, atestado_dict, relatorio = executar_pipeline(
        texto_art, texto_atestado, client, st.container()
    )
except Exception as ex:
    st.error(f"Falha no pipeline: {ex}")
    st.stop()

st.divider()

# Banner
if relatorio.apto_para_cat and relatorio.resultado_global == "APROVADO":
    st.markdown("""<div class="result-banner aprovado">
      <div class="status-indicator"></div>
      <div>
        <div class="status-title">APROVADO — APTO PARA EMISSAO DE CAT</div>
        <div class="status-sub">Todos os criterios de conformidade SITAC/MA foram satisfeitos.</div>
      </div>
    </div>""", unsafe_allow_html=True)
elif relatorio.erros_criticos:
    ids = ", ".join(relatorio.erros_criticos)
    st.markdown(f"""<div class="result-banner reprovado">
      <div class="status-indicator"></div>
      <div>
        <div class="status-title">REPROVADO — NAO SUBMETER AO SITAC</div>
        <div class="status-sub">{len(relatorio.erros_criticos)} erro(s) critico(s): {ids}. Submissao resultara em indeferimento.</div>
      </div>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown("""<div class="result-banner aviso">
      <div class="status-indicator"></div>
      <div>
        <div class="status-title">APROVADO COM RESSALVAS</div>
        <div class="status-sub">Revise os alertas antes de submeter ao SITAC/MA.</div>
      </div>
    </div>""", unsafe_allow_html=True)

# Classificacao
if relatorio.classificacao:
    c = relatorio.classificacao
    st.markdown('<div class="secao">Classificacao dos Documentos — Agente 1</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="classif-grid">
      <div class="classif-cell">
        <div class="classif-label">Tipo da ART</div>
        <div class="classif-val">{c.tipo_art}</div>
        <div class="classif-obs">Qualidade: {c.qualidade_art}</div>
      </div>
      <div class="classif-cell">
        <div class="classif-label">Tipo do Atestado</div>
        <div class="classif-val">{c.tipo_atestado}</div>
        <div class="classif-obs">Qualidade: {c.qualidade_atestado}</div>
      </div>
    </div>
    {"<div style='font-size:0.78rem;color:#3a6080;font-style:italic;'>" + c.observacoes + "</div>" if c.observacoes else ""}
    """, unsafe_allow_html=True)

# Dados extraidos
st.markdown('<div class="secao">Dados Extraidos — Agente 2</div>', unsafe_allow_html=True)
col_a, col_b = st.columns(2, gap="large")

with col_a:
    rows = "".join([
        linha_dado("Numero ART", art_dict.get("numero")),
        linha_dado("CNPJ Contratante", art_dict.get("contratante_cnpj")),
        linha_dado("Razao Social", art_dict.get("contratante_razao_social")),
        linha_dado("Contrato", art_dict.get("contrato_numero")),
        linha_dado("Data Inicio", art_dict.get("data_inicio")),
        linha_dado("Termino Previsto", art_dict.get("data_termino_previsto")),
        linha_dado("Data Baixa", art_dict.get("data_solicitacao_baixa")),
        linha_dado("Data Registro", art_dict.get("data_registro_art")),
        linha_dado("Valor Contrato", f"R$ {art_dict.get('valor_contrato')}" if art_dict.get("valor_contrato") else "—"),
    ] + [
        linha_dado("Atividade", f'{a.get("descricao","")} — {a.get("quantidade","")} {a.get("unidade","")}')
        for a in art_dict.get("atividades", [])
    ])
    st.markdown(f'<div class="data-block"><div class="block-title">ART — Anotacao de Responsabilidade Tecnica</div>{rows}</div>', unsafe_allow_html=True)

with col_b:
    rows = "".join([
        linha_dado("CNPJ Emitente", atestado_dict.get("emitente_cnpj")),
        linha_dado("Razao Social", atestado_dict.get("emitente_razao_social")),
        linha_dado("Contrato", atestado_dict.get("contrato_numero")),
        linha_dado("ART Referenciada", atestado_dict.get("art_referenciada")),
        linha_dado("Periodo Inicio", atestado_dict.get("data_inicio_periodo")),
        linha_dado("Periodo Termino", atestado_dict.get("data_termino_periodo")),
        linha_dado("Data Emissao", atestado_dict.get("data_emissao")),
    ] + [
        linha_dado("Atividade", f'{a.get("descricao","")} — {a.get("quantidade","")} {a.get("unidade","")}')
        for a in atestado_dict.get("atividades", [])
    ])
    st.markdown(f'<div class="data-block"><div class="block-title">Atestado de Capacidade Tecnica</div>{rows}</div>', unsafe_allow_html=True)

# Verificacoes
st.markdown('<div class="secao">Verificacoes de Conformidade SITAC/MA — Agentes 3 + Camada Deterministica</div>', unsafe_allow_html=True)

for v in relatorio.verificacoes:
    if v.status == "CONFORME":
        cls, badge_cls, badge_txt = "conforme", "badge-conforme", "CONFORME"
    elif v.status == "ERRO_CRITICO":
        cls, badge_cls, badge_txt = "erro", "badge-erro", "ERRO CRITICO"
    else:
        cls, badge_cls, badge_txt = "alerta", "badge-alerta", "ALERTA"

    origem_cls = "badge-det" if v.origem == "DETERMINISTICO" else "badge-ia"
    origem_lbl = "DETERMINISTICO" if v.origem == "DETERMINISTICO" else "IA"

    st.markdown(f"""<div class="verif-card {cls}">
      <div class="verif-header">
        <div><span class="verif-id">{v.id}</span><span class="verif-regra">{v.regra}</span></div>
        <div class="verif-badges">
          <span class="verif-badge {origem_cls}">{origem_lbl}</span>
          <span class="verif-badge {badge_cls}">{badge_txt}</span>
        </div>
      </div>
      <div class="verif-valores">Encontrado: {v.valor_encontrado or "—"} &nbsp;|&nbsp; Esperado: {v.valor_esperado or "—"}</div>
      <div class="verif-detalhe">{v.detalhe}</div>
    </div>""", unsafe_allow_html=True)

# Referencias normativas
if relatorio.referencias_normativas:
    st.markdown('<div class="secao">Fundamentacao Normativa — Agente 4</div>', unsafe_allow_html=True)
    for r in relatorio.referencias_normativas:
        st.markdown(f"""<div class="norma-card">
          <div class="norma-id">{r.id_verificacao}</div>
          <div>
            <div class="norma-resolucao">{r.resolucao}</div>
            <div class="norma-artigo">{r.artigo}</div>
            <div class="norma-ementa">{r.ementa}</div>
            <div class="norma-consequencia">Consequencia: {r.consequencia}</div>
          </div>
        </div>""", unsafe_allow_html=True)

# Parecer tecnico
if relatorio.parecer:
    p = relatorio.parecer
    apto = "INAPTO" not in p.classificacao_final.upper()
    st.markdown('<div class="secao">Parecer Tecnico Formal — Agente 5</div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="parecer-wrapper">
      <div class="parecer-topo">
        <div class="parecer-orgao">Conselho Regional de Engenharia e Agronomia do Maranhao — CREA-MA</div>
        <div class="parecer-titulo">PARECER TECNICO</div>
        <div class="parecer-numero">N. {p.numero} &nbsp;&middot;&nbsp; {p.data_emissao}</div>
      </div>
      <div class="parecer-secao">Objeto</div>
      <div class="parecer-texto">{p.objeto}</div>
      <div class="parecer-secao">Sintese Documental</div>
      <div class="parecer-texto">{p.sintese_documental}</div>
      <div class="parecer-secao">Analise Tecnica</div>
      <div class="parecer-texto">{p.analise_tecnica}</div>
      <div class="parecer-secao">Conclusao</div>
      <div class="parecer-texto">{p.conclusao}</div>
      <div class="parecer-secao">Recomendacao</div>
      <div class="parecer-texto">{p.recomendacao}</div>
      <div class="parecer-classificacao">
        <span class="classif-tag {'apto' if apto else 'inapto'}">{p.classificacao_final}</span>
      </div>
    </div>""", unsafe_allow_html=True)

if relatorio.recomendacao_final:
    st.markdown('<div class="secao">Recomendacao Final</div>', unsafe_allow_html=True)
    st.info(relatorio.recomendacao_final)

# Export
st.divider()
relatorio_json = {
    "resultado_global": relatorio.resultado_global,
    "apto_para_cat": relatorio.apto_para_cat,
    "classificacao": asdict(relatorio.classificacao) if relatorio.classificacao else None,
    "verificacoes": [asdict(v) for v in relatorio.verificacoes],
    "erros_criticos": relatorio.erros_criticos,
    "referencias_normativas": [asdict(r) for r in relatorio.referencias_normativas],
    "parecer": asdict(relatorio.parecer) if relatorio.parecer else None,
    "recomendacao_final": relatorio.recomendacao_final,
    "gerado_em": relatorio.gerado_em,
    "dados_extraidos": {"art": art_dict, "atestado": atestado_dict},
}

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
_, col_j, col_t, _ = st.columns([1.5, 1, 1, 1.5])

with col_j:
    st.download_button(
        "Exportar JSON Completo",
        data=json.dumps(relatorio_json, ensure_ascii=False, indent=2),
        file_name=f"auditoria_sitac_{ts}.json",
        mime="application/json",
        use_container_width=True,
    )

with col_t:
    if relatorio.parecer:
        st.download_button(
            "Exportar Parecer TXT",
            data=formatar_parecer_txt(relatorio.parecer),
            file_name=f"parecer_{ts}.txt",
            mime="text/plain",
            use_container_width=True,
        )
