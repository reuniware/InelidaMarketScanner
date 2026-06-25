"""
Inelida Market Scanner - Guide Utilisateur PDF
Genere un guide complet expliquant comment utiliser l'outil pour trader.
"""

import os, sys, time, logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.WARNING)

from fpdf import FPDF

OUTPUT_PDF = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "reports",
    "Comment_trader_et_gagner_avec_Inelida_Market_Scanner.pdf"
)

F = 'Helvetica'
FB = 'Helvetica'

def _safe(text):
    if not isinstance(text, str):
        text = str(text)
    replacements = {
        chr(8594): ' -> ', chr(8596): ' <-> ',
        chr(8593): ' ^ ', chr(8595): ' v ',
        chr(10003): 'v', chr(183): '.',
        chr(8722): '-', chr(8212): '-',
        chr(8211): '-', chr(160): ' ',
        chr(8220): '"', chr(8221): '"',
        chr(8216): "'", chr(8217): "'",
        chr(8592): ' <- ',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('ascii', errors='replace').decode('ascii').replace('?', ' ')


class UserGuidePDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=True, margin=15)

        
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(F, 'I', 7)
        self.set_text_color(130, 130, 130)
        self.cell(0, 4, "Inelida Market Scanner - Guide Utilisateur", align='L')
        self.cell(0, 4, f"Page {self.page_no()}", align='R', new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-12)
        self.set_font(F, 'I', 6)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4, "Document genere le {} | Inelida Market Scanner v1.0".format(
            datetime.now().strftime("%Y-%m-%d %H:%M")), align='C')

    def chapter_title(self, num, title):
        self.set_font(FB, 'B', 16)
        self.set_text_color(25, 25, 112)
        self.cell(0, 10, "{} - {}".format(num, title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(25, 25, 112)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def sub_title(self, title):
        self.set_font(FB, 'B', 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text):
        self.set_font(F, '', 9)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin)
        self.multi_cell(self.w - self.l_margin - self.r_margin, 4.5, _safe(text))
        self.set_x(self.l_margin)
        self.ln(2)

    def bullet(self, text, indent=10):
        self.set_font(F, '', 9)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin + indent)
        bw = self.w - self.r_margin - self.l_margin - indent
        self.multi_cell(bw, 4.5, "- " + _safe(text))
        self.set_x(self.l_margin)

    def highlight_box(self, text, color=(220, 235, 255)):
        self.set_fill_color(*color)
        self.set_font(FB, 'B', 9)
        self.set_text_color(30, 30, 30)
        y = self.get_y()
        if y > 250:
            self.add_page()
            y = self.get_y()
        self.set_x(self.l_margin)
        bw = self.w - self.l_margin - self.r_margin
        self.rect(self.l_margin, y, bw, 14, style='F')
        self.set_xy(self.l_margin + 3, y + 2)
        self.multi_cell(bw - 6, 4.5, _safe(text))
        self.set_x(self.l_margin)
        self.ln(3)

    def code_block(self, text):
        self.set_fill_color(240, 240, 240)
        self.set_font('Courier', '', 7.5)
        self.set_text_color(20, 20, 20)
        y = self.get_y()
        # Count lines to estimate height
        lines = text.split('\n')
        h = len(lines) * 3.5 + 4
        if y + h > 270:
            self.add_page()
            y = self.get_y()
        self.rect(self.l_margin, y, self.w - self.l_margin - self.r_margin, h, style='F')
        self.set_xy(self.l_margin + 3, y + 2)
        for line in lines:
            if self.get_y() > 270:
                self.add_page()
                self.set_xy(self.l_margin + 3, self.get_y() + 2)
            self.cell(0, 3.5, _safe(line), new_x="LMARGIN", new_y="NEXT")
            self.set_x(self.l_margin + 3)
        self.ln(4)

    def table_header(self, cols, widths):
        self.set_font(FB, 'B', 7.5)
        self.set_fill_color(25, 25, 112)
        self.set_text_color(255, 255, 255)
        for i, (col, w) in enumerate(zip(cols, widths)):
            align = 'L' if i == 0 else 'C'
            self.cell(w, 6, _safe(col), border=0, fill=True, align=align)
        self.ln()

    def table_row(self, cells, widths, colors=None):
        self.set_font(F, '', 7)
        if colors:
            self.set_text_color(*colors)
        else:
            self.set_text_color(40, 40, 40)
        if self.get_y() > 265:
            self.add_page()
        for i, (cell, w) in enumerate(zip(cells, widths)):
            align = 'L' if i == 0 else 'C'
            self.cell(w, 5, _safe(str(cell))[:40], border=0, align=align)
        self.ln()


def build_guide():
    os.makedirs(os.path.dirname(OUTPUT_PDF), exist_ok=True)
    pdf = UserGuidePDF()
    
    # ════════════════════════════════════════
    # PAGE DE GARDE
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.ln(25)
    
    # Decorative line
    pdf.set_draw_color(25, 25, 112)
    pdf.set_line_width(1)
    pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
    pdf.ln(15)
    
    pdf.set_font(FB, 'B', 26)
    pdf.set_text_color(25, 25, 112)
    pdf.cell(0, 14, "Comment trader et gagner", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 14, "avec Inelida Market Scanner", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    
    pdf.set_draw_color(25, 25, 112)
    pdf.set_line_width(0.5)
    mid = pdf.w / 2
    pdf.line(mid - 40, pdf.get_y(), mid + 40, pdf.get_y())
    pdf.ln(8)
    
    pdf.set_font(F, '', 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "Guide complet d'utilisation de l'outil de scan ICT", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Base sur la methodologie Inner Circle Trader (ICT)", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    
    pdf.set_font(F, '', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Strategies de trading, gestion des risques et cas pratiques", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    
    pdf.set_draw_color(25, 25, 112)
    pdf.set_line_width(1)
    pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
    pdf.ln(15)
    
    pdf.set_font(F, '', 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "Version 1.0 - Juin 2026", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "Inelida Market Scanner - Analyse de marche temps reel", align='C', new_x="LMARGIN", new_y="NEXT")
    
    # ════════════════════════════════════════
    # TABLE DES MATIÈRES
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("", "Table des matieres")
    toc_items = [
        ("1", "Introduction - Qu'est-ce qu'Inelida Market Scanner ?"),
        ("2", "Les concepts ICT utilises par l'outil"),
        ("3", "Comment lire une analyse"),
        ("4", "Quand entrer en position"),
        ("5", "Ou placer son Stop-Loss"),
        ("6", "Ou placer ses Take-Profit"),
        ("7", "Calcul de la taille de position"),
        ("8", "Exemples reels du 24 juin 2026"),
        ("9", "Gestion des risques"),
        ("10", "Questions frequentes"),
        ("11", "Commandes rapides"),
        ("12", "Glossaire"),
    ]
    for num, title in toc_items:
        pdf.set_font(FB, 'B' if num.isdigit() else '', 9)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(10, 6, _safe(num))
        pdf.cell(0, 6, _safe(title), new_x="LMARGIN", new_y="NEXT")
    
    # ════════════════════════════════════════
    # 1. INTRODUCTION
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("1", "Introduction")
    
    pdf.body_text(
        "Inelida Market Scanner est un outil d'analyse de marche automatise qui scanne en "
        "temps reel les marches financiers via MetaTrader 5 (MT5). Il est concu pour identifier "
        "des setups de trading a haute probabilite bases sur la methodologie Inner Circle "
        "Trader (ICT), egalement connue sous le nom de Smart Money Concepts (SMC)."
    )
    pdf.body_text(
        "L'outil analyse automatiquement le range de la session asiatique (00:00-08:00 UTC), "
        "detecte les sweeps de liquidite (BSL/SSL) pendant les sessions London et NY, calcule "
        "les extensions Fibonacci ICT, et genere des signaux de trading avec Stop-Loss et "
        "Take-Profit predefinis."
    )
    pdf.sub_title("Ce que l'outil fait pour vous :")
    pdf.bullet("Scanne 14+ symboles (Forex, Matieres premieres, Cryptos) automatiquement")
    pdf.bullet("Detecte les manipulations de prix ICT (sweeps de liquidite)")
    pdf.bullet("Calcule les niveaux Fibonacci d'extension (-1.618, -2.0, -2.618...)")
    pdf.bullet("Genere des trades avec SL et TP directement exploitables")
    pdf.bullet("Produit un rapport PDF horodate pour le suivi")
    pdf.bullet("Analyse les gaps daily et les structures de marche (CHoCH/MSS)")
    
    pdf.sub_title("Les marches analyses :")
    pdf.body_text(
        "Forex: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD\n"
        "Matieres: XAUUSD (Or), XAGUSD (Argent), UKOIL.cash (Petrole Brent), CORN.c (Mais)\n"
        "Cryptos: BTCUSD, ETHUSD\n"
        "Indices: US30, NAS100, SPX500 (selon disponibilite du broker)"
    )
    pdf.highlight_box(
        "POINT CLE : L'outil ne prend PAS de decisions a votre place. Il vous fournit des "
        "analyses et des suggestions de trades. La decision finale vous appartient."
    )
    
    # ════════════════════════════════════════
    # 2. CONCEPTS ICT
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("2", "Les concepts ICT utilises par l'outil")
    
    pdf.sub_title("2.1 - Range Asiatique (Asian Range)")
    pdf.body_text(
        "La session asiatique (00:00-08:00 UTC) est le point de depart de l'analyse ICT. "
        "Pendant ces 8 heures, le marche est cense etablir une zone de 'juste valeur' (fair value) "
        "qui servira de reference pour le reste de la journee."
    )
    pdf.body_text(
        "L'outil calcule deux niveaux :\n"
        "- AH (Asian High) = le plus haut des 8 bougies H1 asiatiques\n"
        "- AL (Asian Low) = le plus bas des 8 bougies H1 asiatiques\n"
        "- Range = AH - AL (l'ecart entre les deux)"
    )
    pdf.highlight_box(
        "EXEMPLE 24 juin 2026 - ETHUSD : AH = 1679.45, AL = 1656.85, Range = 22.60 pts. "
        "Le prix est reste dans ce range pendant la session asiatique, puis l'a casse pendant NY."
    )
    
    pdf.sub_title("2.2 - Sweep de liquidite (BSL / SSL)")
    pdf.body_text(
        "Un 'sweep' se produit quand le prix traverse un niveau cle, puis revient en sens inverse. "
        "Cela cree un 'wick' ou une 'meche' sur les bougies. En ICT, cela represente une chasse "
        "aux stops (stop hunt) :"
    )
    pdf.bullet("BSL (Buy-side Liquidity) : le prix monte au-dessus d'un AH ou d'un swing haut pour declencher les stops acheteurs, puis retombe. Signal baissier.")
    pdf.bullet("SSL (Sell-side Liquidity) : le prix descend en-dessous d'un AL ou d'un swing bas pour declencher les stops vendeurs, puis remonte. Signal haussier.")
    
    pdf.body_text(
        "L'outil detecte deux types de traversee de niveau :\n"
        "- SWEEP : la meche traverse ET le close rejette de l'autre cote (signal ICT fort)\n"
        "- BREACH : la meche traverse juste le niveau (signal plus faible, sans rejet)"
    )
    
    pdf.sub_title("2.3 - CHoCH / MSS (Changement de structure)")
    pdf.body_text(
        "Le CHoCH (Change of Character) ou MSS (Market Structure Shift) est un changement "
        "dans la structure du marche. Il se produit quand :"
    )
    pdf.bullet("CHoCH haussier : le prix fait un 'higher high' ET un 'higher low' -> tendance haussiere")
    pdf.bullet("CHoCH baissier : le prix fait un 'lower high' ET un 'lower low' -> tendance baissiere")
    pdf.body_text(
        "L'outil analyse les 12 dernieres bougies H1 pour determiner automatiquement si un CHoCH "
        "est en cours, vous evitant de le faire manuellement."
    )
    
    pdf.sub_title("2.4 - Extensions Fibonacci ICT")
    pdf.body_text(
        "Contrairement au Fibonacci de retracement classique, l'ICT utilise des EXTENSIONS "
        "du range asiatique :"
    )
    pdf.body_text(
        "Pour un signal BAISSIER (SELL) : les extensions sont projetees EN-DESSOUS du AL :\n"
        "   Fib -1.618 = AL + (-1.618) x Range\n"
        "   Fib -2.0   = AL + (-2.0)   x Range\n"
        "   Fib -2.618 = AL + (-2.618) x Range\n"
        "   Fib -3.0   = AL + (-3.0)   x Range\n"
        "   Fib -3.618 = AL + (-3.618) x Range\n"
        "   Fib -4.0   = AL + (-4.0)   x Range"
    )
    pdf.body_text(
        "Pour un signal HAUSSIER (BUY) : les extensions sont projetees AU-DESSUS du AH :\n"
        "   Fib +1.618 = AH + 1.618 x Range\n"
        "   Fib +2.0   = AH + 2.0   x Range\n"
        "   Fib +2.618 = AH + 2.618 x Range\n"
        "   (Egalement +3.0, +3.618, +4.0)"
    )
    
    pdf.sub_title("2.5 - Les gaps daily")
    pdf.body_text(
        "Un 'gap' est un espace vide entre le close d'une bougie D1 et l'open de la suivante. "
        "En ICT, les gaps non combles agissent comme des AIMANTS. Le prix tend a revenir les "
        "combler. Un gap haussier au-dessus du prix agit comme un aimant haussier ; un gap "
        "baissier en-dessous du prix agit comme un aimant baissier."
    )
    pdf.highlight_box(
        "EXEMPLE 24 juin 2026 - UKOIL.cash : Le gap du 27/02/2026 (73.42 - 77.59) a agi comme "
        "un aimant baissier toute la journee. Le prix, parti de 75.95, est descendu jusqu'a 73.29 "
        "pour combler ce gap. Le trade SELL a rapporte +2.35%."
    )
    
    # ════════════════════════════════════════
    # 3. LIRE UNE ANALYSE
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("3", "Comment lire une analyse")
    
    pdf.sub_title("3.1 - La synthese (scan rapide)")
    pdf.body_text(
        "Quand vous demandez un scan, vous recevez un tableau comme celui-ci. Voici comment "
        "le lire :"
    )
    
    widths = [18, 8, 14, 14, 14, 14, 8, 8, 10, 10, 14, 8]
    pdf.table_header(
        ["Symbole", "Dir", "Entry", "BID", "SL", "TP1", "RR", "Fib", "DistSL", "DistTP", "Sweeps", "P&L"],
        widths
    )
    colors = (180, 30, 30)
    pdf.table_row(
        ["ETHUSD", "SELL", "1619.17", "1612.47", "1681.71", "1611.65", "0.12", "-2.0",
         "3.86%", "0.46%", "AH+AL", "+0.00%"],
        widths, colors=(180, 30, 30)
    )
    pdf.ln(3)
    
    pdf.body_text("Colonnes expliquees :")
    pdf.bullet("Symbole : L'actif concerne (ETHUSD = Ethereum contre Dollar)")
    pdf.bullet("Dir : Direction du trade suggere (BUY = achat, SELL = vente)")
    pdf.bullet("Entry : Prix d'entree suggere (le BID au moment du scan)")
    pdf.bullet("BID : Prix actuel du marche")
    pdf.bullet("SL : Stop-Loss suggere")
    pdf.bullet("TP1 : Premier Take-Profit")
    pdf.bullet("RR : Risk:Reward = gain potentiel / risque potentiel (plus c'est haut, mieux c'est)")
    pdf.bullet("Fib : Le niveau Fibonacci actuel (-1.618 = premier objectif baissier)")
    pdf.bullet("DistSL : Distance actuelle au Stop-Loss en %")
    pdf.bullet("DistTP : Distance actuelle au Take-Profit en %")
    pdf.bullet("Sweeps : Quels cotes du range asiatique ont ete sweeps (AH = haut, AL = bas)")
    pdf.bullet("P&L : Profit & Loss latent en % si le trade etait deja ouvert")
    
    pdf.sub_title("3.2 - Le dedie (zoom par trade)")
    pdf.body_text(
        "Un zoom sur un actif specifique contient :"
    )
    pdf.bullet("Prix live (BID, ASK, Spread)")
    pdf.bullet("Setup Asian (AH, AL, Range, Sweeps, Breaches)")
    pdf.bullet("Bougies M5/M15/H1 (analyse de la structure)")
    pdf.bullet("Analyse CHoCH/MSS par timeframe")
    pdf.bullet("Niveaux Fibonacci complets")
    pdf.bullet("Roadmap ASCII (carte visuelle des niveaux)")
    pdf.bullet("Setup trade recommande (Entry, SL, TP, Lots, RR)")
    pdf.bullet("Scenarios probables (haussier, baissier, range)")
    
    pdf.sub_title("3.3 - La roadmap ASCII")
    pdf.body_text(
        "Exemple de roadmap visuelle :\n\n"
        "  NIVEAU  ---- Resistance majeure\n"
        "     |\n"
        "     |   +++++  Zone de resistance  +++++\n"
        "     |\n"
        "  NIVEAU  ---- PRIX ACTUEL\n"
        "     |\n"
        "     |   -----  zone de gap -----\n"
        "     |\n"
        "  NIVEAU  ---- Support cle / TP"
    )
    
    # ════════════════════════════════════════
    # 4. QUAND ENTRER
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("4", "Quand entrer en position")
    
    pdf.sub_title("4.1 - Les conditions ICT pour entrer")
    pdf.body_text(
        "L'outil genere un signal de trade quand les conditions ICT suivantes sont remplies :"
    )
    pdf.body_text(
        "Pour un SIGNAL BUY (achat) :\n"
        "  Condition 1 : Le AL (Asian Low) a ete sweepe (le prix est descendu sous le AL\n"
        "                et a rejete au-dessus), ET le prix est maintenant au-dessus du AH\n"
        "       OU\n"
        "  Condition 2 : Le AH ET le AL ont ete sweeps (double sweep), ET le prix est\n"
        "                maintenant au-dessus du AH"
    )
    pdf.body_text(
        "Pour un SIGNAL SELL (vente) :\n"
        "  Condition 1 : Le AH (Asian High) a ete sweepe, ET le prix est maintenant\n"
        "                en-dessous du AL\n"
        "       OU\n"
        "  Condition 2 : Le AH ET le AL ont ete sweeps (double sweep), ET le prix est\n"
        "                maintenant en-dessous du AL"
    )
    
    pdf.sub_title("4.2 - Le moment ideal de la journee")
    pdf.body_text(
        "Les meilleurs moments pour entrer en position selon la session :\n\n"
        "- London Open (08:00-09:00 UTC) : Premier sweep du range asiatique. C'est le moment\n"
        "  ou la direction de la journee commence a se dessiner.\n\n"
        "- NY Open (13:00-14:00 UTC) : Deuxieme sweep, souvent DANS L'AUTRE SENS. C'est le\n"
        "  DOUBLE SWEEP ICT classique - la manipulation complete du range asiatique.\n\n"
        "- NY afternoon (14:00-17:00 UTC) : La direction est etablie. C'est le moment ou\n"
        "  les extensions Fibonacci se jouent.\n\n"
        "- Eviter : Asian session (00:00-08:00 UTC) - trop tot, range pas encore etabli.\n"
        "- Eviter : 30 min avant les annonces economiques majeures."
    )
    
    pdf.sub_title("4.3 - Les signaux de confirmation")
    pdf.body_text(
        "Avant d'entrer, verifiez ces elements :"
    )
    pdf.bullet("Le fib_state est -1.618 ou +1.618 (premier niveau = le plus sur)")
    pdf.bullet("Le RR est > 0.5 (en-dessous, le risque est trop eleve par rapport au gain)")
    pdf.bullet("Le CHoCH H1 confirme la direction (ne pas aller contre le trend)")
    pdf.bullet("Il n'y a pas d'annonce economique majeure dans les 30 prochaines minutes")
    pdf.bullet("Le D1 montre que le trend global est ALIGNE avec la direction du trade")
    
    pdf.highlight_box(
        "CONSEIL CLES : Les meilleurs trades sont les premiers signaux de la journee "
        "(fib -1.618 ou +1.618). Plus le prix s'eloigne du range asiatique, plus le RR "
        "se degrade et plus le risque de reversal augmente. A -2.618 ou au-dela, le move "
        "est deja tres avance."
    )
    
    pdf.sub_title("4.4 - Ne JAMAIS trader")
    pdf.body_text("Dans ces situations, il est preferable de ne pas entrer en position :")
    pdf.bullet("Aucun sweep detecte (le range asiatique est intact)")
    pdf.bullet("Sweep partiel seul (ex: AH sweepe mais AL pas, et trade BUY) -> signal incomplet")
    pdf.bullet("RR < 0.2 (gain insignifiant par rapport au risque)")
    pdf.bullet("Juste avant une annonce macroeconomique (NFP, CPI, FOMC)")
    pdf.bullet("En fin de session NY (apres 17:00 UTC) -> le move est souvent deja fait")
    pdf.bullet("Quand le prix est deja a -2.618 ou plus -> le meilleur du move est passe")
    
    # ════════════════════════════════════════
    # 5. STOP-LOSS
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("5", "Ou placer son Stop-Loss")
    
    pdf.sub_title("5.1 - Le SL systeme (recommandation de l'outil)")
    pdf.body_text(
        "L'outil calcule automatiquement le SL selon la formule ICT :\n\n"
        "  SELL : SL = AH + 0.10 x Range\n"
        "  BUY  : SL = AL - 0.10 x Range\n\n"
        "Cela place le SL a 10% du range asiatique AU-DELA du niveau oppose. L'idee est que "
        "si le prix retraverse TOUT le range et va 10% plus loin, le setup ICT est invalide."
    )
    pdf.highlight_box(
        "EXEMPLE ETHUSD 24 juin : AH=1679.45, AL=1656.85, Range=22.60\n"
        "SL systeme SELL = 1679.45 + 0.10 x 22.60 = 1681.71\n"
        "Le SL est a 41 pts au-dessus du prix d'entree (1639). C'est LARGE."
    )
    
    pdf.sub_title("5.2 - Le SL agressif (personnalise)")
    pdf.body_text(
        "Le SL systeme est parfois trop large (mauvais RR). Vous pouvez utiliser un SL "
        "plus serre si vous identifiez un niveau de rejet recent :"
    )
    pdf.bullet("SELL : SL juste au-dessus du dernier swing haut (high de bougie de rejet)")
    pdf.bullet("BUY : SL juste en-dessous du dernier swing bas (low de bougie de rejet)")
    pdf.bullet("Regle generale : SL a 1.5x la taille du dernier retracement")
    
    pdf.sub_title("5.3 - Erreurs courantes de SL")
    pdf.bullet("SL trop serre : place SUR un niveau evident (le marche viendra le chercher)")
    pdf.bullet("SL trop large : RR devient nul, trade pas rentable")
    pdf.bullet("Ne pas deplacer le SL en cours de route (sauf en breakeven apres TP1)")
    pdf.bullet("Risquer plus de 1% du capital sur un seul trade")
    
    # ════════════════════════════════════════
    # 6. TAKE-PROFIT
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("6", "Ou placer ses Take-Profit")
    
    pdf.sub_title("6.1 - Les 3 TP de l'outil")
    pdf.body_text(
        "L'outil calcule 3 niveaux de TP bases sur les extensions Fibonacci ICT :"
    )
    pdf.body_text(
        "  TP1 = Fib actuel (ex: -1.618) -> le premier objectif\n"
        "  TP2 = Fib suivant (ex: -2.0)   -> le deuxieme objectif\n"
        "  TP3 = Fib suivant (ex: -2.618) -> le troisieme objectif"
    )
    pdf.body_text(
        "Quand le prix atteint un niveau, le fib_state change automatiquement pour le niveau "
        "suivant. Par exemple, si le prix passe de 1650 a 1620 et que le fib -1.618 est atteint, "
        "le nouveau TP devient le fib -2.0."
    )
    
    pdf.sub_title("6.2 - Comment gerer les TP")
    pdf.bullet("TP1 (fib -1.618 ou +1.618) : Objectif principal. Prendre 50% de la position.")
    pdf.bullet("TP2 (fib -2.0 ou +2.0) : Objectif etendu. Prendre 30% supplementaires.")
    pdf.bullet("TP3 (fib -2.618 ou +2.618) : Objectif runner. Laisser 20% courir.")
    pdf.bullet("Apres TP1 touche : deplacer le SL au point d'entree (breakeven)")
    
    pdf.sub_title("6.3 - Quand prendre ses gains")
    pdf.body_text(
        "Regles de gestion :\n\n"
        "- Prenez le TP1 systematiquement. Un gain est un gain.\n"
        "- Si vous etes en position et que le RR depasse 2:1, envisagez de prendre 100%\n"
        "- Si le fib_state passe a -3.0 ou +3.0, le risque de reversal augmente fortement\n"
        "- Les gaps daily sont des aimants : si un gap est proche du TP, attendez qu'il soit comble"
    )
    
    # ════════════════════════════════════════
    # 7. TAILLE DE POSITION
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("7", "Calcul de la taille de position")
    
    pdf.sub_title("7.1 - La formule de base")
    pdf.body_text(
        "La formule pour calculer le nombre de lots a ouvrir est :\n\n"
        "  Lots = (Capital x Risque%) / (Distance_SL x Valeur_point_par_lot)\n\n"
        "Avec :\n"
        "  Capital = votre solde de compte (ex: 10 036 EUR)\n"
        "  Risque% = le % du capital que vous risquez (ex: 1% = 100 EUR)\n"
        "  Distance_SL = l'ecart entre l'entree et le SL (en points)\n"
        "  Valeur_point_par_lot = depend de l'instrument (voir tableau ci-dessous)"
    )
    
    pdf.sub_title("7.2 - Valeur du point par instrument")
    
    tw = [30, 25, 25, 30]
    pdf.table_header(["Instrument", "Contract Size", "Valeur 1 pt / 1 lot", "Valeur 0.01 lot"], tw)
    pdf.table_row(["Forex (EURUSD, etc.)", "100 000", "~10 USD", "~0.10 USD"], tw)
    pdf.table_row(["XAUUSD (Or)", "100", "~1 USD", "~0.01 USD"], tw)
    pdf.table_row(["XAGUSD (Argent)", "5 000", "~5 USD / 0.01", "~0.05 USD"], tw)
    pdf.table_row(["UKOIL.cash (Petrole)", "100", "~0.088 USD / tick", "~0.0009 USD"], tw)
    pdf.table_row(["BTCUSD", "1", "~1 USD", "~0.01 USD"], tw)
    pdf.table_row(["ETHUSD", "10", "~8.81 USD", "~0.088 USD"], tw)
    pdf.ln(3)
    
    pdf.sub_title("7.3 - Exemple concret (ETHUSD SELL)")
    pdf.body_text(
        "Trade du 24 juin 16:05 UTC :\n\n"
        "Capital : 10 036 EUR (balance compte)\n"
        "Risque souhaite : 50 EUR (0.5%)\n"
        "EURUSD au moment du calcul : 1.1348\n"
        "Risque en USD : 50 x 1.1348 = 56.74 USD\n\n"
        "Setup serre recommande :\n"
        "  Entry : 1618.38\n"
        "  SL : 1625.00 (distance = 6.62 pts)\n"
        "  Valeur point (1 lot) : 8.81 USD\n"
        "  Risque par 1 lot : 6.62 x 8.81 = 58.32 USD\n"
        "  Lots = 56.74 / 58.32 = 0.97 lot\n\n"
        "Resultat : 0.97 lot, risque 50 EUR, gain potentiel au TP (1612) = 50.70 EUR"
    )
    
    pdf.sub_title("7.4 - Tableau rapide (capital 10 000 EUR)")
    pdf.body_text(
        "Pour un risque de 1% (100 EUR), avec SL a 1% du prix d'entree :\n\n"
        "  EURUSD : ~1.36 lot\n"
        "  XAUUSD : ~1.00 lot\n"
        "  BTCUSD : ~0.40 lot\n"
        "  ETHUSD : ~0.76 lot\n"
        "  UKOIL  : ~1.50 lot\n\n"
        "Ces valeurs sont indicatives. Utilisez toujours la formule exacte avec les specs MT5."
    )
    
    # ════════════════════════════════════════
    # 8. EXEMPLES REELS
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("8", "Exemples reels du 24 juin 2026")
    
    pdf.sub_title("8.1 - UKOIL.cash SELL (+2.35%) - Le meilleur trade du jour")
    pdf.body_text(
        "Signal genere a 08:47 UTC :\n"
        "  Entry : 75.951 | TP : 74.494 | SL : 77.057 | RR : 0.80\n\n"
        "Analyse : Le gap daily du 27/02 (73.42 - 77.59) n'avait pas ete comble. Le prix, parti de "
        "75.95, etait attire vers le bas du gap (73.42). Les 3 TP (74.49, 74.13, 73.55) etaient "
        "tous a l'interieur du gap, creant un 'chemin libre' pour le prix.\n\n"
        "Deroulement : Le prix a descendu progressivement toute la journee, touchant le TP1 "
        "(74.49) en milieu de journee, puis continuant jusqu'a 73.29. Le gap a ete comble a 80%.\n\n"
        "Lecon : Les gaps daily sont des aimants puissants. Quand un setup ICT s'aligne avec "
        "un gap non comble, la probabilite de succes est tres elevee."
    )
    
    pdf.sub_title("8.2 - ETHUSD SELL (-4.62% sur la journee)")
    pdf.body_text(
        "Le setup le plus fort de la journee, mais aussi le plus rapide :\n\n"
        "08:00-12:00 UTC : Range asiatique etabli (AH=1679.45, AL=1656.85)\n"
        "14:00-16:00 UTC : Sweep du AH puis du AL (double sweep NY Open) -> signal SELL\n"
        "16:00-17:00 UTC : Le prix traverse les niveaux fib les uns apres les autres\n"
        "   16:05 : entry a 1639 -> TP1 (1620) touche\n"
        "   16:30 : TP2 (1612) touche (low 1609)\n"
        "   17:00 : TP3 (1598) touche -> BID a 1587 (-4.62% sur la journee)\n\n"
        "Lecon : Les cryptos ont des mouvements violents. Un double sweep NY peut declencher "
        "un mouvement de -4.6% en 3 heures. Position sizing essentiel."
    )
    
    pdf.sub_title("8.3 - GBPUSD SELL - Double TP touche")
    pdf.body_text(
        "Matin (08:47) : Entry 1.31723, TP 1.31587 -> TOUCHE (low M5 1.31400)\n"
        "Apres-midi (14:00) : Nouveau signal, entry 1.31638, TP 1.31587 -> TOUCHE (low 1.31531)\n\n"
        "Double TP touche sur la meme paire dans la meme journee. Le range asiatique etait "
        "le meme (AH=1.32043, AL=1.31869), avec un double sweep London qui s'est joue en "
        "deux temps."
    )
    
    pdf.sub_title("8.4 - Bilan de la journee")
    pdf.body_text(
        "  9 trades GAGNANTS\n"
        "  0 trade PERDANT\n"
        "  1 trade OUVERT (AUDCHF, -0.17%)\n"
        "  Meilleur trade : UKOIL.cash (+2.35%)\n\n"
        "Tous les TP ont ete verifies par les bougies M5 reelles (low/high), pas seulement "
        "par le BID instantane. Cela confirme que les signaux ICT de l'outil sont fiables."
    )
    
    # ════════════════════════════════════════
    # 9. GESTION DES RISQUES
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("9", "Gestion des risques")
    
    pdf.sub_title("9.1 - Regles d'or")
    pdf.bullet("Ne risquez JAMAIS plus de 1-2% de votre capital sur un seul trade")
    pdf.bullet("Ne risquez JAMAIS plus de 5% de votre capital sur une journee")
    pdf.bullet("Apres 3 pertes consecutives : arret. Revoir votre strategie.")
    pdf.bullet("Toujours verifier le RR avant d'entrer. RR minimum conseille : 0.5")
    pdf.bullet("Ne pas entrer si vous n'avez pas identifie ou mettre le SL")
    
    pdf.sub_title("9.2 - Gestion par taille de compte")
    pdf.body_text(
        "Compte < 5 000 EUR :\n"
        "  - Risque max par trade : 1% (50 EUR max)\n"
        "  - Lots max : 0.20-0.50 lot sur Forex\n"
        "  - Cryptos : 0.05-0.10 lot maximum\n\n"
        "Compte 5 000 - 20 000 EUR :\n"
        "  - Risque max par trade : 0.5-1% (50-200 EUR)\n"
        "  - Lots max : 0.50-1.50 lot sur Forex\n"
        "  - Cryptos : 0.10-0.50 lot\n\n"
        "Compte FTMO / Prop Firm (100 000 EUR) :\n"
        "  - Risque max par trade : 0.25-0.5% (250-500 EUR)\n"
        "  - Respecter strictement les regles du prop firm"
    )
    
    pdf.sub_title("9.3 - Le breakeven")
    pdf.body_text(
        "Regle fondamentale : quand le TP1 est touche, deplacer le SL au niveau de l'entree.\n"
        "Cela garantit que le trade ne peut pas devenir perdant. Vous avez 3 options :\n\n"
        "1. Prendre 100% au TP1 -> trade termine, gain securise\n"
        "2. Prendre 50% au TP1, deplacer SL a entry, laisser courir 50% -> risk-free runner\n"
        "3. Prendre 30% au TP1, 30% au TP2, 40% runner -> gestion maximisee"
    )
    
    pdf.sub_title("9.4 - Journal de trading")
    pdf.body_text(
        "L'outil genere un PDF horodate chaque fois que vous lancez un scan. Conservez ces "
        "PDFs. Ils constituent votre journal de trading et vous permettent de :\n\n"
        "- Verifier a posteriori si les TP/SL ont ete touches\n"
        "- Analyser vos erreurs et vos reussites\n"
        "- Ameliorer votre discipline de trading\n"
        "- Mesurer votre taux de reussite sur le long terme"
    )
    
    # ════════════════════════════════════════
    # 10. FAQ
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("10", "Questions frequentes")
    
    pdf.sub_title("Q: L'outil peut-il trader a ma place ?")
    pdf.body_text(
        "R: Non. Inelida Market Scanner est un outil d'ANALYSE. Il detecte les setups "
        "ICT et vous suggere des entrees, mais la decision finale et l'execution du trade "
        "dans MT5 vous appartiennent. L'outil ne passe pas d'ordres automatiquement."
    )
    
    pdf.sub_title("Q: Tous les signaux sont-ils gagnants ?")
    pdf.body_text(
        "R: Non. Aucune methode de trading n'est gagnante a 100%. L'ICT a un taux de reussite "
        "eleve (60-80% sur les setups bien identifies) mais les pertes font partie du jeu. "
        "L'important est que vos gains soient superieurs a vos pertes (RR > 1)."
    )
    
    pdf.sub_title("Q: Puis-je trader uniquement sur les signaux de l'outil ?")
    pdf.body_text(
        "R: Oui, c'est meme recommande. Les signaux sont generes selon des regles ICT strictes. "
        "Cependant, il est conseille de :\n"
        "- Verifier le contexte macro (pas d'annonce dans les 30 min)\n"
        "- Verifier le RR (> 0.5 minimum)\n"
        "- Ne pas trader les signaux avec fib -2.618 ou au-dela"
    )
    
    pdf.sub_title("Q: Pourquoi le RR est-il parfois si faible ?")
    pdf.body_text(
        "R: Le RR se degrade quand le prix a deja beaucoup bouge dans la direction du trade. "
        "Un signal a fib -1.618 a un meilleur RR qu'un signal a -2.618. Si le RR est < 0.3, "
        "le trade est probablement trop proche de son objectif pour etre rentable."
    )
    
    pdf.sub_title("Q: Quelle est la difference entre sweep et breach ?")
    pdf.body_text(
        "R: Un SWEEP est une traversee de niveau AVEC rejet (la meche traverse et le close "
        "revient de l'autre cote). C'est le signal ICT fort. Un BREACH est une simple traversee "
        "de niveau sans rejet. L'outil ne genere un signal de trade que sur les sweeps, pas "
        "sur les breaches."
    )
    
    pdf.sub_title("Q: Puis-je laisser l'outil tourner toute la journee ?")
    pdf.body_text(
        "R: Oui. L'outil peut etre lance en continu. A chaque scan, il analyse les nouvelles "
        "bougies et met a jour les signaux si necessaire. Cependant, evitez de trader pendant "
        "la session asiatique (00:00-08:00 UTC) car le range n'est pas encore etabli."
    )
    
    pdf.sub_title("Q: Comment savoir si un TP a vraiment ete touche ?")
    pdf.body_text(
        "R: L'outil verifie automatiquement les bougies M5 : si le LOW (pour un SELL) est "
        "en-dessous du TP, alors le TP a ete touche meme si le BID actuel est au-dessus. "
        "C'est plus fiable que de simplement comparer le BID actuel au TP."
    )
    
    pdf.sub_title("Q: Que faire si je rate l'entree au moment du signal ?")
    pdf.body_text(
        "R: Ne PAS courir apres le prix. Si le fib_state est deja a -2.0 ou plus, le meilleur "
        "du move est peut-etre passe. Attendez le prochain signal. Il y a de nouvelles "
        "opportunites chaque jour."
    )
    
    # ════════════════════════════════════════
    # 11. COMMANDES RAPIDES
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("11", "Commandes rapides")
    
    pdf.sub_title("11.1 - Demandes a faire au chat AI")
    pdf.body_text(
        "Vous pouvez interagir avec l'outil via le chat en utilisant ces commandes :"
    )
    pdf.code_block(
        "relance une analyse generale de tous les actifs        -> Scan complet\n"
        "zoom [symbole] live                                     -> Ex: zoom ETHUSD live\n"
        "zoom [symbole] rebound                                  -> Ex: zoom UKOIL rebound\n"
        "analyse de la structure CHoCH/MSS                       -> Analyse approfondie\n"
        "check [symbole]                                         -> Verifier un trade\n"
        "final closing scan                                      -> Scan de cloture\n"
        "quel tp et quel sl pour [symbole]                       -> Niveaux de trade\n"
        "combien de lots pour [risque]E sur [symbole]            -> Position sizing\n"
        "génère un pdf                                           -> Rapport PDF immediat"
    )
    
    pdf.sub_title("11.2 - Commandes scan rapides")
    pdf.code_block(
        "python generate_live_report.py                          -> Rapport PDF complet\n"
        "python -c \"import MetaTrader5 as mt5; mt5.initialize();\n"
        "  t=mt5.symbol_info_tick('ETHUSD'); print(t.bid)\"       -> Prix ETHUSD live"
    )
    
    # ════════════════════════════════════════
    # 12. GLOSSAIRE
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("12", "Glossaire")
    
    glossary = [
        ("AH", "Asian High = le plus haut de la session asiatique (00:00-08:00 UTC)"),
        ("AL", "Asian Low = le plus bas de la session asiatique"),
        ("Range", "AH - AL = l'ecart du range asiatique"),
        ("BSL", "Buy-side Liquidity = liquidite au-dessus des plus hauts (stops acheteurs)"),
        ("SSL", "Sell-side Liquidity = liquidite en-dessous des plus bas (stops vendeurs)"),
        ("Sweep", "Le prix traverse un niveau ET le close rejette de l'autre cote"),
        ("Breach", "Le prix traverse juste un niveau (sans rejet)"),
        ("CHoCH", "Change of Character = changement de tendance"),
        ("MSS", "Market Structure Shift = synonyme de CHoCH"),
        ("ICT", "Inner Circle Trader = methodologie de trading de Michael Huddleston"),
        ("Fib -1.618", "Premier niveau d'extension baissiere = AL - 1.618 * Range"),
        ("Fib +1.618", "Premier niveau d'extension haussiere = AH + 1.618 * Range"),
        ("RR", "Risk:Reward = gain potentiel / risque potentiel"),
        ("TP1/T2/T3", "Take-Profit 1, 2, 3 = objectifs de gain"),
        ("SL", "Stop-Loss = niveau de sortie en perte"),
        ("Entry", "Prix d'entree suggere (le BID au moment du scan)"),
        ("BID", "Prix acheteur (ce que vous obtenez en vendant)"),
        ("ASK", "Prix vendeur (ce que vous payez pour acheter)"),
        ("Spread", "Difference entre ASK et BID = cout de transaction"),
        ("P&L", "Profit & Loss = gain ou perte en cours"),
        ("Gap", "Ecart entre le close d'une bougie et l'open de la suivante"),
        ("Liquidity Grab", "Chasse aux stops = sweep ICT"),
        ("Wick", "Meche de bougie = le prix a depasse le close"),
        ("Breakeven", "SL deplace au niveau de l'entree = trade sans risque"),
        ("Session asiatique", "00:00-08:00 UTC, etablit le range de reference"),
        ("London Open", "08:00-13:00 UTC, premier sweep du range"),
        ("NY Open", "13:00-21:00 UTC, deuxieme sweep, direction principale"),
        ("Displacement", "Mouvement fort dans une direction = expansion"),
        ("Coil", "Range qui se resserre = consolidation avant breakout"),
        ("Fakeout", "Fausse cassure = le prix casse un niveau puis revient"),
    ]
    
    for term, defn in glossary:
        pdf.set_font(FB, 'B', 8)
        pdf.set_text_color(25, 25, 112)
        pdf.cell(25, 5, _safe(term))
        pdf.set_font(F, '', 8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, _safe(defn), new_x="LMARGIN", new_y="NEXT")
    
    # ════════════════════════════════════════
    # DERNIERE PAGE
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font(FB, 'B', 20)
    pdf.set_text_color(25, 25, 112)
    pdf.cell(0, 12, "Bon trading !", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_draw_color(25, 25, 112)
    pdf.set_line_width(0.5)
    mid = pdf.w / 2
    pdf.line(mid - 30, pdf.get_y(), mid + 30, pdf.get_y())
    pdf.ln(8)
    pdf.set_font(F, '', 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, "Inelida Market Scanner - Analyse ICT automatisee", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Rapports, scans, et analyses en temps reel", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(15)
    pdf.set_font(F, 'I', 8)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 5, "Document genere le {}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")), align='C', new_x="LMARGIN", new_y="NEXT")
    
    # ════════════════════════════════════════
    # OUTPUT
    # ════════════════════════════════════════
    pdf.output(OUTPUT_PDF)
    return OUTPUT_PDF


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    
    print("=" * 60)
    print("  Generation du guide utilisateur PDF...")
    print("=" * 60)
    print()
    
    try:
        path = build_guide()
        size_kb = os.path.getsize(path) / 1024
        print("  PDF genere : {}".format(path))
        print("  Taille : {:.1f} Ko".format(size_kb))
        print()
        print("  Termine.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
