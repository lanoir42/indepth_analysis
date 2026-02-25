from pydantic import BaseModel


class NewsThumbnail(BaseModel):
    url: str
    width: int = 0
    height: int = 0


class NewsArticle(BaseModel):
    title: str
    publisher: str
    link: str
    published: str = ""
    thumbnail: NewsThumbnail | None = None


class CalendarEvent(BaseModel):
    date: str
    event: str
    details: str = ""
