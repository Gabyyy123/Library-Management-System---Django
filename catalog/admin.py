from django.contrib import admin
from .models import UserProfile, Category, Book, BorrowRecord, Computer, MeetingRoomSchedule

# Registering your models so they appear in the Django Admin panel
admin.site.register(UserProfile)
admin.site.register(Category)
admin.site.register(Book)
admin.site.register(BorrowRecord)
admin.site.register(Computer)
admin.site.register(MeetingRoomSchedule)