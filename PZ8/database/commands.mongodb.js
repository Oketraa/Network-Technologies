// mongosh "mongodb://127.0.0.1:27017/planner" database/commands.mongodb.js
// Выполнять на учебной базе: пример создаёт и удаляет только свою запись.
const result = db.events.insertOne({title: "Mongo shell demo", image: "",
  description: "Практическая №9", tags: ["mongodb"], location: "Уфа"});
const id = result.insertedId;
printjson(db.events.findOne({_id: id}));
printjson(db.events.find({tags: "mongodb"}).toArray());
db.events.updateOne({_id: id}, {$set: {location: "Hybrid"}});
printjson(db.events.findOne({_id: id}));
db.events.deleteOne({_id: id});
printjson(db.events.findOne({_id: id})); // null
printjson(db.users.getIndexes()); // уникальный email_1 после запуска API
printjson(db.users.find({}, {email: 1, username: 1, events: 1}).toArray());
// Регистрацию выполняйте через /user/signup.
// Для просмотра всех событий без изменения данных:
// db.events.find().pretty()
// Связанные события удаляйте через API: оно очищает DBRef в users.events.
