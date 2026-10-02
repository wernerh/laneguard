def greeting_html(name):
    # SEEDED VULN VA-3: user input interpolated into HTML without escaping (XSS).
    return "<p>Hello, " + name + "!</p>"
