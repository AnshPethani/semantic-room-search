std_msgs/Header header          # frame_id = "map"
string label                    # from the detector vocabulary
float32 confidence
geometry_msgs/Point position    # object position in the map frame
string room_id                  # room containing the point; empty if outside all rooms
string source                   # "yolo" or "oracle"
