from indepth_analysis.skills.euro_macro.monthly_brief import research


def test_requires_receipt_not_file_size(tmp_path):
    output, receipt = tmp_path/'report.md', tmp_path/'receipt.json'
    output.write_text('partial failure output' * 1000)
    assert not research._completed(output, 'input', receipt)
    research._save_completion(output, 'input', receipt)
    assert research._completed(output, 'input', receipt)
    assert not research._completed(output, 'changed input', receipt)
    output.write_text('modified')
    assert not research._completed(output, 'input', receipt)


def test_corrupt_receipt_is_not_success(tmp_path):
    output, receipt = tmp_path/'report.md', tmp_path/'receipt.json'
    output.write_text('text'); receipt.write_text('{broken')
    assert not research._completed(output, 'input', receipt)
