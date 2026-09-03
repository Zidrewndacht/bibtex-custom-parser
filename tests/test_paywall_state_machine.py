from shared import db


def test_paywall_added_and_removed(test_db):
    with db.get_db() as conn:
        conn.execute("INSERT INTO papers (id, title) VALUES ('p1', 'T')")
    
    db.update_paper_custom_fields('p1', {'user_trace': 'This is paywalled'})
    assert db.get_paper_by_id('p1')['pdf_state'] == 'paywalled'
    
    db.update_paper_custom_fields('p1', {'user_trace': 'Found it on sci-hub'})
    assert db.get_paper_by_id('p1')['pdf_state'] == 'none'

def test_paywall_state_trap_with_pdf(test_db):
    """After the fix: if a PDF exists and the paywall text is removed,
    the state should transition to 'PDF', not stay stuck on 'paywalled'."""
    with db.get_db() as conn:
        conn.execute("""
            INSERT INTO papers (id, title, pdf_filename, pdf_state)
            VALUES ('p1', 'T', 'p1.pdf', 'paywalled')
        """)

    db.update_paper_custom_fields('p1', {'user_trace': 'Actually I have the PDF now'})
    p = db.get_paper_by_id('p1')

    # FIXED BEHAVIOR: PDF existence takes priority over the paywall note
    assert p['pdf_state'] == 'PDF'