from enum import Enum
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
import meilisearch
import uvicorn
# -(auth)---------------------------------
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import datetime, timedelta

app = FastAPI()
client = meilisearch.Client("http://localhost:7700", "my_secret_key")
users_idx = client.index("users")
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def extract_json_from_doc(doc):
  return dict(doc)["_Document__doc"]

# since this one is not exposed to the user,
# I don't see a point in inheriting it from BaseModel
# and wasting time on implementing pydantic's stuff for it
class User:
  username: str
  tasks_idx: meilisearch.index.Index
  def __init__(self, username: str, tasks_idx: meilisearch.index.Index):
    self.username = username
    self.tasks_idx = tasks_idx

  def get_and_update_task_id(self):
    user = users_idx.get_document(self.username)
    new_task_id = user.curr_max_task_id + 1
    user = extract_json_from_doc(user)
    user.update({ "curr_max_task_id": new_task_id })
    users_idx.update_documents([user])
    return new_task_id


class Auth(BaseModel):
  username: str
  password: str
 

SECRET_KEY = "UnèðJöSU£h|Ç×Ï½«c¹þM¬js7£êé¬ºÇLàQ2ã<¥µæâãP1}Æ¬ÞÉ2òË$pÂÔ7ðãµ¯÷4Ù¡u(Õ\á8¾ªÈ\\7ÓðëmçïÊ;@>b¿Þz]@¸¾L%aýÝÙyàôH¥dõ7|usBÞ¬ª_²X.MÏK$N3½`zÈ"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

@app.post("/signup", summary="Create new user")
def create_user(data: Auth):
  # querying database to check if user already exist
  try:
    user = users_idx.get_document(data.username)
  except:
    user = None

  if user is not None:
      raise HTTPException(
      status_code = 400,
      detail = "This username is already taken"
    )
  user = {
    "username": data.username,
    "curr_max_task_id": 0,
    "password": pwd_ctx.hash(data.password),
  }
  # add the user to the db and set their name as primary key
  # (necessary when creating the 1st user, and then does nothing)
  users_idx.add_documents([user], "username") 
  return { "username": data.username }

@app.post("/login", summary="Returns user's access token")
async def login(data: OAuth2PasswordRequestForm = Depends()):
  err = HTTPException(
    status_code = 400,
    detail = "Incorrect username or password"
  )
  try:
    user = users_idx.get_document(data.username)
  except:
    raise err

  hashed_pass = user.password
  if not pwd_ctx.verify(data.password, hashed_pass):
    raise err

  expires_delta = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
  encoded_jwt = jwt.encode({
    "exp": expires_delta,
    "sub": user.username
  }, SECRET_KEY)
  return { "access_token": encoded_jwt }

def get_current_user(token: str = Depends(OAuth2PasswordBearer(tokenUrl="login"))):
  err = HTTPException(
    status_code = 401,
    detail = "Can't validate token; re-login"
  )
  try:
    payload = jwt.decode(token, SECRET_KEY)
    username: str = payload.get("sub")
    if not username:
      raise err
  except:
    raise err
  try:
    user = users_idx.get_document(username)
  except:
    raise err
  idx = client.index(f"todos-{username}")
  idx.update_sortable_attributes([
        "id",
        "title",
        "body",
        "status",
        "priority"
      ])
  return User(username, idx);
  

# -(end auth)-----------------------------


class TaskAction(str, Enum):
  update = "update"
  delete = "delete"

class TaskStatus(str, Enum):
  todo    = "todo"
  started = "started"
  done    = "done"

class Task(BaseModel):
  title: str | None = None
  body: str | None = None
  status: TaskStatus = TaskStatus.todo
  #date: datetime
  priority: int = 0

class SortingOrder(str, Enum):
  asc = "asc"
  desc = "desc"

class SortingSchema(BaseModel):
  id: SortingOrder | None = None
  title: SortingOrder | None = None
  body: SortingOrder | None = None
  status: SortingOrder | None = None
  priority: SortingOrder | None = None

  def get_sorts(self):
    sorts = []
    #if self.id:
    #  sorts += f"id:{self.id.lower()}"
    if self.title:
      sorts.append(f"title:{self.title.lower()}")
    if self.body:
      sorts.append(f"body:{self.body.lower()}")
    if self.status:
      sorts.append(f"status:{self.status.lower()}")
    if self.priority:
      sorts.append(f"priority:{self.priority.lower()}")
    return sorts



# -------------------------------------------------------------------

curr_max_id = 2

@app.post("/tasks/new")
def tasks_new(task: Task, user = Depends(get_current_user)):
  if not task.title:
    raise HTTPException(
      status_code = 422,
      detail = "Title must be specified when creating new tasks"
    )
  
  doc = { "id": user.get_and_update_task_id() }
  doc.update(
    {k: v for k, v in task.dict().items() if v}
  )
  user.tasks_idx.add_documents([doc])
  return doc


# TODO: rm me, or raise an exception
def find_item(id: int, tasks_idx):
  try:
    return tasks_idx.get_document(id)
  except:
    return None


@app.post("/tasks/{id}/{action}")
def tasks_action_update(id: int, action: TaskAction, task: Task = {}, user = Depends(get_current_user)):
  doc = find_item(id, user.tasks_idx)
  if doc:
    match action:
      case TaskAction.update:
        doc = { "id": doc.id }
        doc.update(
          {k: v for k, v in task.dict().items() if v}
        )
        user.tasks_idx.update_documents([doc])
      case TaskAction.delete:
        user.tasks_idx.delete_document(doc.id)
  else:
    raise HTTPException(
      status_code=404,
      detail=f"Task with id {id} does not exist"
    )

@app.get("/tasks/{id}")
def tasks_main(id: int, user = Depends(get_current_user)):
  doc = find_item(id, user.tasks_idx)
  if doc:
    return extract_json_from_doc(doc)
  else:
    raise HTTPException(
      status_code = 404,
      detail = f"Task with id {id} does not exist"
    )

@app.get("/tasks")
def tasks_main(user = Depends(get_current_user)):
    return search("", None, user)


@app.post("/search")
# TODO: add sorting and pagination
def search(query: str = "", sort: SortingSchema | None = None, user = Depends(get_current_user)):
  sorts = []
  if sort:
    sorts += sort.get_sorts()
  try:
    hits = user.tasks_idx.search(query, {
      # show everything
      "limit": user.tasks_idx.get_stats().number_of_documents,
      "sort": sorts,
    })["hits"]
  except: # Index has not yet been created
    hits = None

  return hits if hits else []

if __name__ == "__main__":
  uvicorn.run("main:app", reload = True)
