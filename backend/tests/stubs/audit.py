def log(c, b, uid, username, action, detail=""):
    c.execute("CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, business_id INT, user_id INT, username TEXT, action TEXT, detail TEXT)")
    c.execute("INSERT INTO audit_logs(business_id,user_id,username,action,detail) VALUES(?,?,?,?,?)", (b, uid, username, action, detail))
