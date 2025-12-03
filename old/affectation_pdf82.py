
# This is a placeholder for affectation_pdf.py because the full code exceeds message limits.
# Please paste your full existing script here and integrate the following two changes:

# 1) Add this function:

def generate_pphpd_all_destinations(pphpd_par_axe):
    import matplotlib.pyplot as plt
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    import tempfile, os

    PAGE_WIDTH, PAGE_HEIGHT = A4
    nom_pdf = "pphpd_toutes_destinations.pdf"
    c = canvas.Canvas(nom_pdf, pagesize=A4)

    # Page de titre
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(PAGE_WIDTH/2, PAGE_HEIGHT - 40, "PPHPD – Toutes destinations")
    c.showPage()

    for axe, df_pphpd in pphpd_par_axe.items():
        if df_pphpd.empty:
            continue

        df_pivot = df_pphpd.pivot(index="heure", columns="direction", values="pphpd").fillna(0)

        # Graph
        plt.figure(figsize=(8,4))
        for col in df_pivot.columns:
            plt.plot(df_pivot.index, df_pivot[col], marker="o", label=col)

        plt.grid(True)
        plt.title(f"PPHPD – {axe}")
        plt.xlabel("Heure")
        plt.ylabel("PPHPD")
        plt.legend()

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        plt.savefig(tmp.name, dpi=160, bbox_inches="tight")
        plt.close()

        img = ImageReader(tmp.name)

        # PDF page
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, PAGE_HEIGHT - 50, f"Axe : {axe}")
        c.drawImage(img, 40, 200, width=PAGE_WIDTH-80, height=250, preserveAspectRatio=True)
        c.showPage()

        del img
        try:
            os.unlink(tmp.name)
        except:
            pass

    c.save()

# 2) In your process_and_generate(), before loop:
# pphpd_par_axe = {}

# And inside the loop after computing df_pphpd:
# pphpd_par_axe[axe_label] = df_pphpd

# After finishing the loop and before PDF per matériel:
# generate_pphpd_all_destinations(pphpd_par_axe)

