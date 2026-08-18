from django.urls import path
from .views import CustomerNoteListCreateView, CustomerNoteDeleteView

urlpatterns = [
    path("<int:user_id>/", CustomerNoteListCreateView.as_view(), name="customer-notes"),
    path("note/<int:note_id>/", CustomerNoteDeleteView.as_view(), name="customer-note-delete"),
]